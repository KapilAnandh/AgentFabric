from __future__ import annotations

from typing import TYPE_CHECKING

from .checkpoint import CheckpointManager

if TYPE_CHECKING:
    from runtime.executor.dag import WorkflowDAG


class RollbackController:
    """Controls workflow rollback and recovery operations."""

    def __init__(self) -> None:
        self.checkpoint_manager = CheckpointManager()

    async def rollback_workflow(
        self,
        workflow_id: str,
        dag: "WorkflowDAG",
        lifecycle_manager,
        resource_manager,
    ) -> dict:
        """
        Rollback a failed workflow to the last checkpoint.

        Args:
            workflow_id: Workflow identifier
            dag: Workflow DAG instance
            lifecycle_manager: AgentLifecycleManager instance
            resource_manager: ResourceManager instance

        Returns:
            Dict with rollback status and resume information
        """
        # Load checkpoint
        checkpoint = await self.checkpoint_manager.load_checkpoint(workflow_id)

        if checkpoint is None:
            return {
                "status": "no_checkpoint",
                "action": "restart",
            }

        # Terminate all running agents
        await lifecycle_manager.terminate_all(workflow_id)

        # Release all resources
        agents = await lifecycle_manager.list_agents(workflow_id=workflow_id)
        for agent in agents:
            try:
                await resource_manager.release_resources(agent.agent_id)
            except Exception:
                # Continue even if resource release fails
                pass

        # Reset failed tasks to PENDING
        from runtime.lifecycle.states import TaskState

        for task_id, data in dag.graph.nodes(data=True):
            if data.get("status") == TaskState.FAILED.value:
                dag.mark_task_pending(task_id)

        return {
            "status": "rolled_back",
            "resume_from": checkpoint["step_name"],
            "progress": checkpoint["progress"],
            "checkpoint_id": checkpoint["checkpoint_id"],
        }
