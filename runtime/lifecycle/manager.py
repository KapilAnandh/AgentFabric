from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

from memory.config_loader import get_config
from memory.postgres.db import execute, fetch
from memory.postgres.exceptions import DatabaseUnavailableError
from memory.redis.client import RedisClient
from router import select_model

from .agent_model import AgentRecord
from .states import AgentState, is_valid_transition


logger = logging.getLogger(__name__)


class AgentLifecycleManager:
    def __init__(self) -> None:
        self.config = get_config()
        self.redis = RedisClient()
        self.default_token_budget = self.config["memory"]["token_budget_default"]

    async def create_agent(
        self,
        workflow_id,
        task_type,
        token_budget=None,
    ) -> AgentRecord:
        agent_id = str(uuid4())
        model_key, model_name = select_model(task_type, available_vram_gb=22.0)
        agent = AgentRecord(
            agent_id=agent_id,
            state=AgentState.CREATED,
            model_name=model_name,
            model_key=model_key,
            workflow_id=str(workflow_id),
            task_type=task_type,
            token_budget=token_budget or self.default_token_budget,
        )

        await self._save_agent(agent)
        return agent

    async def transition(self, agent_id, new_state, error_text=None) -> AgentRecord:
        agent = await self.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")

        target_state = new_state if isinstance(new_state, AgentState) else AgentState(new_state)
        if not is_valid_transition(agent.state, target_state):
            raise ValueError(f"Invalid transition: {agent.state} -> {target_state}")

        now = datetime.utcnow()
        agent.state = target_state

        if target_state == AgentState.RUNNING and agent.started_at is None:
            agent.started_at = now
        if target_state in {AgentState.COMPLETED, AgentState.FAILED, AgentState.TERMINATED}:
            agent.completed_at = now
        if target_state == AgentState.RETRYING:
            agent.retry_count += 1
            agent.completed_at = None

        if error_text is not None:
            agent.error_text = error_text

        await self._save_agent(agent)
        return agent

    async def get_agent(self, agent_id) -> AgentRecord | None:
        cache_key = self._redis_key(agent_id)
        cached = await self.redis.get_state(cache_key)
        if cached is not None:
            return AgentRecord.model_validate(cached)

        try:
            query = """
                SELECT
                    agent_id,
                    state,
                    model_name,
                    model_key,
                    workflow_id,
                    task_type,
                    gpu_slot,
                    tokens_used,
                    token_budget,
                    started_at,
                    completed_at,
                    error_text,
                    created_at,
                    retry_count,
                    max_retries
                FROM agents
                WHERE agent_id = $1
                LIMIT 1
            """
            rows = await fetch(query, UUID(str(agent_id)))
            if not rows:
                return None

            agent = self._row_to_agent(rows[0])
            await self.redis.set_state(cache_key, agent.model_dump(mode="json"), ttl=86400)
            return agent
        except DatabaseUnavailableError as e:
            logger.warning(f"Database unavailable when fetching agent {agent_id}: {e}")
            raise

    async def list_agents(self, workflow_id=None, state=None) -> list[AgentRecord]:
        try:
            query = """
                SELECT
                    agent_id,
                    state,
                    model_name,
                    model_key,
                    workflow_id,
                    task_type,
                    gpu_slot,
                    tokens_used,
                    token_budget,
                    started_at,
                    completed_at,
                    error_text,
                    created_at,
                    retry_count,
                    max_retries
                FROM agents
                WHERE 1 = 1
            """
            params = []

            if workflow_id is not None:
                params.append(UUID(str(workflow_id)))
                query += f" AND workflow_id = ${len(params)}"
            if state is not None:
                state_value = state.value if isinstance(state, AgentState) else str(state)
                params.append(state_value)
                query += f" AND state = ${len(params)}"

            query += " ORDER BY created_at DESC"
            rows = await fetch(query, *params)
            return [self._row_to_agent(row) for row in rows]
        except DatabaseUnavailableError as e:
            logger.warning(f"Database unavailable when listing agents: {e}")
            raise

    async def terminate_all(self, workflow_id) -> int:
        try:
            agents = await self.list_agents(workflow_id=workflow_id)
            terminated_count = 0
            now = datetime.utcnow()

            for agent in agents:
                if agent.state in {AgentState.COMPLETED, AgentState.TERMINATED}:
                    continue

                agent.state = AgentState.TERMINATED
                agent.completed_at = now
                await self._save_agent(agent)
                terminated_count += 1

            return terminated_count
        except DatabaseUnavailableError as e:
            logger.warning(f"Database unavailable when terminating agents for workflow {workflow_id}: {e}")
            raise

    async def _save_agent(self, agent: AgentRecord) -> None:
        await self.redis.set_state(
            self._redis_key(agent.agent_id),
            agent.model_dump(mode="json"),
            ttl=86400,
        )

        try:
            query = """
                INSERT INTO agents (
                    agent_id,
                    state,
                    model_name,
                    model_key,
                    workflow_id,
                    task_type,
                    gpu_slot,
                    tokens_used,
                    token_budget,
                    started_at,
                    completed_at,
                    error_text,
                    created_at,
                    retry_count,
                    max_retries
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
                )
                ON CONFLICT (agent_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    model_name = EXCLUDED.model_name,
                    model_key = EXCLUDED.model_key,
                    workflow_id = EXCLUDED.workflow_id,
                    task_type = EXCLUDED.task_type,
                    gpu_slot = EXCLUDED.gpu_slot,
                    tokens_used = EXCLUDED.tokens_used,
                    token_budget = EXCLUDED.token_budget,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    error_text = EXCLUDED.error_text,
                    created_at = EXCLUDED.created_at,
                    retry_count = EXCLUDED.retry_count,
                    max_retries = EXCLUDED.max_retries
            """
            await execute(
                query,
                UUID(str(agent.agent_id)),
                str(agent.state.value),
                str(agent.model_name),
                str(agent.model_key),
                UUID(str(agent.workflow_id)),
                str(agent.task_type),
                str(agent.gpu_slot) if agent.gpu_slot else None,
                agent.tokens_used,
                agent.token_budget,
                agent.started_at,
                agent.completed_at,
                str(agent.error_text) if agent.error_text else None,
                agent.created_at,
                agent.retry_count,
                agent.max_retries,
            )
        except DatabaseUnavailableError as e:
            logger.warning(f"Database unavailable when saving agent {agent.agent_id}, cached in Redis only: {e}")

    @staticmethod
    def _redis_key(agent_id) -> str:
        return f"agent:{agent_id}"

    @staticmethod
    def _row_to_agent(row) -> AgentRecord:
        return AgentRecord(
            agent_id=str(row["agent_id"]),
            state=row["state"],
            model_name=row["model_name"],
            model_key=row["model_key"],
            workflow_id=str(row["workflow_id"]),
            task_type=row["task_type"],
            gpu_slot=row["gpu_slot"],
            tokens_used=row["tokens_used"] or 0,
            token_budget=row["token_budget"] or 4000,
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error_text=row["error_text"],
            created_at=row["created_at"],
            retry_count=row["retry_count"] or 0,
            max_retries=row["max_retries"] or 3,
        )
