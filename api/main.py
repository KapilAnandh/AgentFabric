from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.planner import PlannerAgent
from agents.registry import AgentRegistry
from memory.config_loader import get_config
from memory.postgres.db import close_pool, fetch, get_pool
from memory.postgres.exceptions import DatabaseUnavailableError
from memory.redis.client import RedisClient
from observability import init_tracer
from observability.metrics import start_metrics_server
from openwebui import call_model, test_connection
from router.model_router.scorer import TASK_MODEL_PREFERENCES, score_model
from runtime.executor import WorkflowExecutor
from runtime.lifecycle.manager import AgentLifecycleManager
from runtime.scheduler import ResourceManager


logger = logging.getLogger(__name__)


APP_VERSION = "1.0.0"
APP_START_TIME = time.time()
TASK_TYPES = ["coding", "medical", "research", "qa", "report", "embedding", "general"]


class WorkflowRequest(BaseModel):
    goal: str
    context: dict = Field(default_factory=dict)


class TransitionRequest(BaseModel):
    new_state: str


class ModelTestRequest(BaseModel):
    model_name: str
    prompt: str


def _build_agent_runner(lifecycle_manager: AgentLifecycleManager, resource_manager: ResourceManager, task_type: str):
    async def _runner(agent_id: str, task: dict) -> dict:
        agent_record = await lifecycle_manager.get_agent(agent_id)
        if agent_record is None:
            raise ValueError(f"Agent not found: {agent_id}")

        agent = AgentRegistry.get_agent(
            task_type=task_type,
            agent_id=agent_id,
            model_name=agent_record.model_name,
            token_manager=resource_manager.token_manager,
        )
        result = await agent.run(task["name"], task)
        if isinstance(result, dict):
            return result
        return {
            "type": task_type,
            "result": str(result),
            "agent_id": agent_id,
        }

    return _runner


def _build_agent_registry(lifecycle_manager: AgentLifecycleManager, resource_manager: ResourceManager) -> dict:
    registry = {}
    for task_type in AgentRegistry.get_available_types():
        registry[task_type] = _build_agent_runner(lifecycle_manager, resource_manager, task_type)
    return registry


async def _postgres_ok() -> bool:
    try:
        pool = await get_pool()
        if pool is None:
            return False
        rows = await fetch("SELECT 1 AS ok")
        return bool(rows)
    except DatabaseUnavailableError:
        return False
    except Exception as e:
        logger.debug(f"Postgres health check failed: {e}")
        return False


async def _redis_ok(redis_client: RedisClient) -> bool:
    try:
        return bool(await redis_client._client.ping())
    except Exception:
        return False


async def _openwebui_ok() -> bool:
    try:
        return await test_connection()
    except Exception:
        return False


def _serialize_agent(agent) -> dict:
    if agent is None:
        return {}
    if hasattr(agent, "model_dump"):
        return agent.model_dump(mode="json")
    return dict(agent)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_tracer()
    try:
        start_metrics_server(9090)
    except OSError:
        pass

    app.state.config = get_config()
    app.state.redis = RedisClient()
    app.state.lifecycle_manager = AgentLifecycleManager()
    app.state.resource_manager = ResourceManager()
    app.state.agent_registry = _build_agent_registry(app.state.lifecycle_manager, app.state.resource_manager)
    app.state.planner_agent = PlannerAgent()
    app.state.workflow_executor = WorkflowExecutor(
        app.state.lifecycle_manager,
        app.state.resource_manager,
        app.state.agent_registry,
    )

    try:
        await get_pool()
        app.state.postgres_available = True
        logger.info("PostgreSQL connection established during startup")
    except DatabaseUnavailableError as e:
        app.state.postgres_available = False
        logger.warning(f"PostgreSQL unavailable during startup: {e}")
    except Exception as e:
        app.state.postgres_available = False
        logger.error(f"Unexpected error during PostgreSQL startup check: {e}")

    try:
        await app.state.redis._client.ping()
        app.state.redis_available = True
    except Exception as e:
        app.state.redis_available = False
        logger.warning(f"Redis unavailable during startup: {e}")

    yield

    try:
        await close_pool()
    finally:
        try:
            await app.state.redis._client.aclose()
        except Exception:
            pass


app = FastAPI(title="Agent Runtime Platform", version=APP_VERSION, lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
async def health():
    redis_client = app.state.redis
    postgres = await _postgres_ok()
    redis = await _redis_ok(redis_client)
    openwebui = await _openwebui_ok()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "services": {
            "postgres": postgres,
            "redis": redis,
            "openwebui": openwebui,
        },
    }


@app.post("/workflow")
async def run_workflow(request: WorkflowRequest):
    try:
        workflow_id = str(uuid4())
        dag = await app.state.planner_agent.plan(request.goal, request.context)
        return await app.state.workflow_executor.execute_workflow(workflow_id, dag)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(exc)}") from exc


@app.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    try:
        workflow_uuid = UUID(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workflow_id") from exc

    try:
        workflow_rows = await fetch(
            """
            SELECT workflow_id, name, status, created_at, completed_at
            FROM workflows
            WHERE workflow_id = $1
            LIMIT 1
            """,
            workflow_uuid,
        )
        if not workflow_rows:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow_row = workflow_rows[0]
        task_rows = await fetch(
            """
            SELECT task_id, name, task_type, model_used, status, result_json,
                   started_at, completed_at,
                   EXTRACT(EPOCH FROM (completed_at - started_at)) AS duration_seconds
            FROM tasks
            WHERE workflow_id = $1
            ORDER BY started_at ASC
            """,
            workflow_uuid,
        )

        tasks = []
        for task_row in task_rows:
            result_json = task_row["result_json"]
            if isinstance(result_json, str):
                with_result = json.loads(result_json)
            else:
                with_result = result_json or {}

            tasks.append(
                {
                    "task_id": str(task_row["task_id"]),
                    "name": task_row["name"],
                    "task_type": task_row["task_type"],
                    "model_used": task_row["model_used"],
                    "status": task_row["status"],
                    "started_at": task_row["started_at"].isoformat() if task_row["started_at"] else None,
                    "completed_at": task_row["completed_at"].isoformat() if task_row["completed_at"] else None,
                    "duration_seconds": float(task_row["duration_seconds"]) if task_row["duration_seconds"] else 0.0,
                    "result": with_result.get("result", ""),
                }
            )

        total_duration_seconds = 0.0
        if workflow_row["created_at"] and workflow_row["completed_at"]:
            total_duration_seconds = (workflow_row["completed_at"] - workflow_row["created_at"]).total_seconds()

        return {
            "workflow_id": str(workflow_row["workflow_id"]),
            "name": workflow_row["name"],
            "status": workflow_row["status"],
            "created_at": workflow_row["created_at"].isoformat() if workflow_row["created_at"] else None,
            "completed_at": workflow_row["completed_at"].isoformat() if workflow_row["completed_at"] else None,
            "total_duration_seconds": total_duration_seconds,
            "tasks": tasks,
        }
    except DatabaseUnavailableError as e:
        logger.error(f"Database unavailable for workflow {workflow_id}: {e}")
        raise HTTPException(
            status_code=503, detail="Database service unavailable. Please try again later."
        ) from e


@app.get("/workflows")
async def list_workflows():
    try:
        rows = await fetch(
            """
            SELECT
                w.workflow_id,
                w.name,
                w.status,
                w.created_at,
                w.completed_at,
                COUNT(t.task_id) AS task_count
            FROM workflows w
            LEFT JOIN tasks t ON w.workflow_id = t.workflow_id
            GROUP BY w.workflow_id, w.name, w.status, w.created_at, w.completed_at
            ORDER BY w.created_at DESC
            LIMIT 20
            """
        )
        return [
            {
                "workflow_id": str(row["workflow_id"]),
                "name": row["name"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "task_count": int(row["task_count"] or 0),
            }
            for row in rows
        ]
    except DatabaseUnavailableError as e:
        logger.error(f"Database unavailable when listing workflows: {e}")
        raise HTTPException(
            status_code=503, detail="Database service unavailable. Please try again later."
        ) from e


@app.get("/agents")
async def list_agents():
    try:
        agents = await app.state.lifecycle_manager.list_agents()
        return [_serialize_agent(agent) for agent in agents]
    except DatabaseUnavailableError as e:
        logger.error(f"Database unavailable when listing agents: {e}")
        raise HTTPException(
            status_code=503, detail="Database service unavailable. Please try again later."
        ) from e


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    try:
        agent = await app.state.lifecycle_manager.get_agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _serialize_agent(agent)
    except DatabaseUnavailableError as e:
        logger.error(f"Database unavailable when fetching agent {agent_id}: {e}")
        raise HTTPException(
            status_code=503, detail="Database service unavailable. Please try again later."
        ) from e


@app.post("/agents/{agent_id}/transition")
async def transition_agent(agent_id: str, request: TransitionRequest):
    try:
        agent = await app.state.lifecycle_manager.transition(agent_id, request.new_state)
        return _serialize_agent(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailableError as e:
        logger.error(f"Database unavailable when transitioning agent {agent_id}: {e}")
        raise HTTPException(
            status_code=503, detail="Database service unavailable. Please try again later."
        ) from e


@app.get("/system/status")
async def system_status():
    status = app.state.resource_manager.get_system_status()
    status["uptime_seconds"] = int(time.time() - APP_START_TIME)
    status["active_agents"] = status["active_agents_count"]
    status["postgres_available"] = getattr(app.state, "postgres_available", False)
    status["redis_available"] = getattr(app.state, "redis_available", False)
    return status


@app.get("/models")
async def models():
    config = app.state.config
    models_config = config["models"]
    response = []
    for model_key, model_config in models_config.items():
        scores = {task_type: score_model(model_key, task_type, 22.0) for task_type in TASK_TYPES}
        preferred_for = sorted(
            task_type
            for task_type, preferred_models in TASK_MODEL_PREFERENCES.items()
            if model_key in preferred_models
        )
        response.append(
            {
                "model_key": model_key,
                "name": model_config["name"],
                "vram_gb": model_config["vram_gb"],
                "capabilities": model_config["capabilities"],
                "latency_ms": model_config["latency_ms"],
                "preferred_for": preferred_for,
                "scores": scores,
            }
        )
    return response


@app.post("/test/model")
async def test_model(request: ModelTestRequest):
    response = await call_model(
        model_name=request.model_name,
        messages=[{"role": "user", "content": request.prompt}],
    )
    return {
        "model_name": request.model_name,
        "response": response,
    }


@app.get("/metrics")
async def metrics():
    return RedirectResponse(url="http://localhost:9090/metrics")
