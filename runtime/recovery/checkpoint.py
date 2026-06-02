from __future__ import annotations

import json
from typing import Optional
from uuid import UUID, uuid4

from memory.postgres.db import execute, fetch
from memory.redis.client import RedisClient


class CheckpointManager:
    """Manages workflow checkpoints for recovery and resumption."""

    def __init__(self) -> None:
        self.redis = RedisClient()

    async def save_checkpoint(
        self,
        workflow_id: str,
        step_name: str,
        progress: float,
        model_name: str,
        state: dict,
    ) -> str:
        """
        Save a workflow checkpoint to Redis and PostgreSQL.

        Args:
            workflow_id: Unique workflow identifier
            step_name: Name of the current step
            progress: Progress percentage (0-100)
            model_name: Model being used
            state: Additional state data

        Returns:
            checkpoint_id: Generated checkpoint UUID
        """
        checkpoint_id = str(uuid4())

        checkpoint_data = {
            "checkpoint_id": checkpoint_id,
            "workflow_id": workflow_id,
            "step_name": step_name,
            "progress": progress,
            "model_name": model_name,
            "state": state,
        }

        # Save to Redis with 24-hour TTL
        redis_key = f"checkpoint:{workflow_id}"
        await self.redis.set_state(redis_key, checkpoint_data, ttl=86400)

        # Save to PostgreSQL for persistence
        query = """
            INSERT INTO checkpoints (
                checkpoint_id,
                workflow_id,
                step_name,
                progress,
                model_name,
                state_json,
                created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
            ON CONFLICT (workflow_id) DO UPDATE SET
                checkpoint_id = EXCLUDED.checkpoint_id,
                step_name = EXCLUDED.step_name,
                progress = EXCLUDED.progress,
                model_name = EXCLUDED.model_name,
                state_json = EXCLUDED.state_json,
                created_at = EXCLUDED.created_at
        """
        await execute(
            query,
            UUID(checkpoint_id),
            UUID(workflow_id),
            str(step_name),
            progress,
            str(model_name),
            json.dumps(state),
        )

        return checkpoint_id

    async def load_checkpoint(self, workflow_id: str) -> Optional[dict]:
        """
        Load a workflow checkpoint, trying Redis first then PostgreSQL.

        Args:
            workflow_id: Unique workflow identifier

        Returns:
            Checkpoint data dict or None if not found
        """
        # Try Redis first (fast path)
        redis_key = f"checkpoint:{workflow_id}"
        cached = await self.redis.get_state(redis_key)
        if cached is not None:
            return cached

        # Fallback to PostgreSQL
        query = """
            SELECT
                checkpoint_id,
                workflow_id,
                step_name,
                progress,
                model_name,
                state_json,
                created_at
            FROM checkpoints
            WHERE workflow_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """
        rows = await fetch(query, UUID(workflow_id))
        if not rows:
            return None

        row = rows[0]
        checkpoint_data = {
            "checkpoint_id": row["checkpoint_id"],
            "workflow_id": row["workflow_id"],
            "step_name": row["step_name"],
            "progress": float(row["progress"]),
            "model_name": row["model_name"],
            "state": json.loads(row["state_json"]) if row["state_json"] else {},
        }

        # Warm up Redis cache
        await self.redis.set_state(redis_key, checkpoint_data, ttl=86400)

        return checkpoint_data

    async def delete_checkpoint(self, workflow_id: str) -> None:
        """
        Delete a workflow checkpoint from Redis and PostgreSQL.

        Args:
            workflow_id: Unique workflow identifier
        """
        # Delete from Redis
        redis_key = f"checkpoint:{workflow_id}"
        await self.redis.delete_state(redis_key)

        # Delete from PostgreSQL
        query = "DELETE FROM checkpoints WHERE workflow_id = $1"
        await execute(query, UUID(workflow_id))
