from __future__ import annotations

import asyncio
import json
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from memory.postgres.db import execute
from observability import (
    record_task_complete,
    record_task_fail,
    record_task_start,
    trace_operation,
    update_system_metrics,
)
from runtime.lifecycle.states import AgentState, TaskState, WorkflowStatus
from runtime.recovery.checkpoint import CheckpointManager
from runtime.recovery.retry import RetryController
from runtime.recovery.rollback import RollbackController

from .dag import WorkflowDAG


class WorkflowExecutor:
    def __init__(self, lifecycle_manager, resource_manager, agent_registry) -> None:
        self.lifecycle_manager = lifecycle_manager
        self.resource_manager = resource_manager
        self.agent_registry = agent_registry
        self.checkpoint_manager = CheckpointManager()
        self.retry_controller = RetryController(max_retries=3, backoff_seconds=5)
        self.rollback_controller = RollbackController()

    async def execute_workflow(self, workflow_id, dag: WorkflowDAG, max_parallel=3) -> dict:
        workflow_start = datetime.utcnow()
        all_results: list[dict] = []

        try:
            dag.validate()
            workflow_uuid = UUID(str(workflow_id))

            checkpoint = await self.checkpoint_manager.load_checkpoint(str(workflow_uuid))
            if checkpoint:
                for task_id, data in dag.graph.nodes(data=True):
                    if data["name"] == checkpoint["step_name"]:
                        predecessors = list(dag.graph.predecessors(task_id))
                        for predecessor_id in predecessors:
                            dag.mark_task_done(predecessor_id)
                        break

            await self._save_workflow(workflow_uuid, dag, WorkflowStatus.RUNNING)

            while True:
                if self._has_failed_tasks(dag):
                    await self._save_workflow(workflow_uuid, dag, WorkflowStatus.FAILED)
                    workflow_end = datetime.utcnow()
                    total_duration = (workflow_end - workflow_start).total_seconds()
                    return self._build_result(
                        workflow_uuid,
                        dag,
                        WorkflowStatus.FAILED,
                        total_duration,
                        all_results,
                    )

                if self._all_tasks_completed(dag):
                    await self._save_workflow(workflow_uuid, dag, WorkflowStatus.COMPLETED)
                    workflow_end = datetime.utcnow()
                    total_duration = (workflow_end - workflow_start).total_seconds()
                    return self._build_result(
                        workflow_uuid,
                        dag,
                        WorkflowStatus.COMPLETED,
                        total_duration,
                        all_results,
                    )

                ready_tasks = dag.get_ready_tasks()[:max_parallel]
                if not ready_tasks:
                    await asyncio.sleep(0)
                    continue

                progress_made = False
                for task in ready_tasks:
                    task_result = await self._run_task(workflow_uuid, dag, task)
                    if task_result is not None:
                        all_results.append(task_result)
                        progress_made = True
                    if self._has_failed_tasks(dag):
                        break

                if not progress_made:
                    await asyncio.sleep(0)
        except Exception as exc:
            workflow_end = datetime.utcnow()
            total_duration = (workflow_end - workflow_start).total_seconds()
            return {
                "workflow_id": str(workflow_id),
                "status": "FAILED",
                "error": str(exc),
                "tasks_completed": 0,
                "tasks_failed": 0,
                "total_duration_seconds": total_duration,
                "task_results": all_results,
            }

    async def execute_task(self, agent_id, task: dict) -> dict:
        task_start = datetime.utcnow()
        task_type = task["task_type"]
        agent_record = await self.lifecycle_manager.get_agent(agent_id)
        if agent_record is None:
            raise ValueError(f"Agent not found: {agent_id}")

        model_name = agent_record.model_name
        record_task_start(task_type)

        with trace_operation("execute_task", {"task_type": task_type, "agent_id": str(agent_id)}):
            handler = self.agent_registry.get(task_type) or self.agent_registry.get("general")
            if handler is None:
                raise ValueError(f"No agent registered for task type: {task_type}")

            if callable(handler):
                result_data = handler(agent_id, task)
                if asyncio.iscoroutine(result_data):
                    result_data = await result_data
            elif hasattr(handler, "execute_task"):
                result_data = await handler.execute_task(agent_id, task)
            elif hasattr(handler, "run"):
                result_data = await handler.run(task["name"], task)
            else:
                raise ValueError(f"Unsupported agent handler for task type: {task_type}")

        task_end = datetime.utcnow()
        duration_seconds = (task_end - task_start).total_seconds()

        if isinstance(result_data, dict):
            result_text = result_data.get("result", "")
            result_payload = dict(result_data)
        else:
            result_text = str(result_data)
            result_payload = {"result": result_text}

        tokens_used = int(result_payload.get("tokens_used", 0))
        agent_record.tokens_used += tokens_used
        await self.lifecycle_manager._save_agent(agent_record)

        stored_result = {
            "type": task_type,
            "result": result_text,
            "model": model_name,
            "duration_seconds": duration_seconds,
            "tokens_used": tokens_used,
        }
        await execute(
            "UPDATE tasks SET result_json=$1::jsonb, model_used=$2, tokens_used=$3 WHERE task_id=$4",
            json.dumps(stored_result),
            model_name,
            tokens_used,
            UUID(task["db_task_id"]),
        )

        result_payload["type"] = task_type
        result_payload["result"] = result_text
        result_payload["model"] = model_name
        result_payload["duration_seconds"] = duration_seconds
        result_payload["agent_id"] = str(agent_id)
        result_payload["task_id"] = task["task_id"]
        return result_payload

    async def _run_task(self, workflow_id: UUID, dag: WorkflowDAG, task: dict) -> dict | None:
        agent = await self.lifecycle_manager.create_agent(
            workflow_id=str(workflow_id),
            task_type=task["task_type"],
        )
        await self.lifecycle_manager.transition(agent.agent_id, AgentState.READY)

        resource_result = await self.resource_manager.request_resources(
            agent_id=agent.agent_id,
            model_key=agent.model_key,
            task_type=task["task_type"],
            token_budget=agent.token_budget,
        )

        if resource_result["status"] == "queued":
            await self.lifecycle_manager.transition(agent.agent_id, AgentState.QUEUED)
            return None

        task_db_id = uuid5(NAMESPACE_URL, f"{workflow_id}:{task['task_id']}")
        task["db_task_id"] = str(task_db_id)
        task["workflow_id"] = str(workflow_id)

        await self.lifecycle_manager.transition(agent.agent_id, AgentState.QUEUED)
        await self.lifecycle_manager.transition(agent.agent_id, AgentState.RUNNING)
        dag.graph.nodes[task["task_id"]]["status"] = TaskState.RUNNING.value

        task_started_at = datetime.utcnow()
        await self._create_task_record(task_db_id, workflow_id, agent.agent_id, agent.model_name, task, task_started_at)

        try:
            result_dict = await self.execute_task(agent.agent_id, task)
            task_completed_at = datetime.utcnow()

            dag.mark_task_done(task["task_id"])
            await self.lifecycle_manager.transition(agent.agent_id, AgentState.COMPLETED)
            await self._finalize_task_record(
                task_db_id,
                TaskState.COMPLETED,
                task_completed_at,
                result_dict,
                agent.model_name,
            )
            record_task_complete(task["task_type"], agent.model_name, result_dict["duration_seconds"])

            completed_tasks = sum(
                1
                for _, data in dag.graph.nodes(data=True)
                if data.get("status") == TaskState.COMPLETED.value
            )
            total_tasks = len(dag.graph.nodes)
            progress = (completed_tasks / total_tasks) * 100 if total_tasks else 0.0

            await self.checkpoint_manager.save_checkpoint(
                workflow_id=str(workflow_id),
                step_name=task["name"],
                progress=progress,
                model_name=agent.model_name,
                state={"task_id": task["task_id"], "completed_tasks": completed_tasks},
            )

            return result_dict
        except Exception as exc:
            task_completed_at = datetime.utcnow()
            duration_seconds = (task_completed_at - task_started_at).total_seconds()
            failure_result = {
                "type": task["task_type"],
                "result": str(exc),
                "model": agent.model_name,
                "duration_seconds": duration_seconds,
                "agent_id": agent.agent_id,
                "task_id": task["task_id"],
                "error": True,
            }

            record_task_fail(task["task_type"])
            dag.mark_task_failed(task["task_id"])
            await self.lifecycle_manager.transition(agent.agent_id, AgentState.FAILED, error_text=str(exc))
            await self._finalize_task_record(
                task_db_id,
                TaskState.FAILED,
                task_completed_at,
                failure_result,
                agent.model_name,
            )

            should_retry = await self.retry_controller.should_retry(agent.agent_id, self.lifecycle_manager)
            if should_retry:
                await self.retry_controller.increment_retry(agent.agent_id, self.lifecycle_manager)
                await self.retry_controller.wait_before_retry(agent.retry_count + 1)
                dag.mark_task_pending(task["task_id"])
            else:
                await self.rollback_controller.rollback_workflow(
                    workflow_id=str(workflow_id),
                    dag=dag,
                    lifecycle_manager=self.lifecycle_manager,
                    resource_manager=self.resource_manager,
                )

            return failure_result
        finally:
            await self.resource_manager.release_resources(agent.agent_id)
            system_status = self.resource_manager.get_system_status()
            update_system_metrics(
                system_status["active_agents_count"],
                system_status["gpu"]["used"],
                system_status["queue_size"],
            )

    async def _save_workflow(self, workflow_id: UUID, dag: WorkflowDAG, status: WorkflowStatus) -> None:
        query = """
            INSERT INTO workflows (workflow_id, name, status, dag_json, completed_at)
            VALUES ($1, $2, $3, $4::jsonb, CASE WHEN $3 IN ('COMPLETED', 'FAILED') THEN NOW() ELSE NULL END)
            ON CONFLICT (workflow_id) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                dag_json = EXCLUDED.dag_json,
                completed_at = CASE
                    WHEN EXCLUDED.status IN ('COMPLETED', 'FAILED') THEN NOW()
                    ELSE workflows.completed_at
                END
        """
        await execute(
            query,
            workflow_id,
            f"Workflow {workflow_id}",
            status.value,
            dag.to_json(),
        )

    async def _create_task_record(
        self,
        task_db_id: UUID,
        workflow_id: UUID,
        agent_id: str,
        model_name: str,
        task: dict,
        started_at: datetime,
    ) -> None:
        query = """
            INSERT INTO tasks (
                task_id,
                workflow_id,
                agent_id,
                name,
                task_type,
                status,
                model_used,
                tokens_used,
                started_at,
                completed_at,
                result_json
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL, NULL)
            ON CONFLICT (task_id) DO UPDATE SET
                agent_id = EXCLUDED.agent_id,
                name = EXCLUDED.name,
                task_type = EXCLUDED.task_type,
                status = EXCLUDED.status,
                model_used = EXCLUDED.model_used,
                tokens_used = EXCLUDED.tokens_used,
                started_at = EXCLUDED.started_at,
                completed_at = NULL,
                result_json = NULL
        """
        await execute(
            query,
            task_db_id,
            workflow_id,
            UUID(str(agent_id)),
            task["name"],
            task["task_type"],
            TaskState.RUNNING.value,
            model_name,
            0,
            started_at,
        )

    async def _finalize_task_record(
        self,
        task_db_id: UUID,
        status: TaskState,
        completed_at: datetime,
        result: dict,
        model_name: str,
    ) -> None:
        query = """
            UPDATE tasks
            SET status = $1,
                completed_at = $2,
                model_used = $3,
                result_json = $4::jsonb
            WHERE task_id = $5
        """
        await execute(
            query,
            status.value,
            completed_at,
            model_name,
            json.dumps(result),
            task_db_id,
        )

    @staticmethod
    def _all_tasks_completed(dag: WorkflowDAG) -> bool:
        return all(
            data.get("status") == TaskState.COMPLETED.value
            for _, data in dag.graph.nodes(data=True)
        )

    @staticmethod
    def _has_failed_tasks(dag: WorkflowDAG) -> bool:
        return any(
            data.get("status") == TaskState.FAILED.value
            for _, data in dag.graph.nodes(data=True)
        )

    @staticmethod
    def _build_result(
        workflow_id: UUID,
        dag: WorkflowDAG,
        status: WorkflowStatus,
        total_duration: float,
        all_results: list[dict],
    ) -> dict:
        tasks_completed = sum(
            1
            for _, data in dag.graph.nodes(data=True)
            if data.get("status") == TaskState.COMPLETED.value
        )
        tasks_failed = sum(
            1
            for _, data in dag.graph.nodes(data=True)
            if data.get("status") == TaskState.FAILED.value
        )
        return {
            "workflow_id": str(workflow_id),
            "status": status.value,
            "tasks_completed": tasks_completed,
            "tasks_failed": tasks_failed,
            "total_duration_seconds": total_duration,
            "task_results": all_results,
        }
