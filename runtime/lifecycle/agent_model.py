from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .states import AgentState


class AgentRecord(BaseModel):
    agent_id: str
    state: AgentState
    model_name: str
    model_key: str
    workflow_id: str
    task_type: str
    gpu_slot: str | None = None
    tokens_used: int = 0
    token_budget: int = 4000
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_text: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = 0
    max_retries: int = 3
