from __future__ import annotations

from enum import Enum


class AgentState(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    TERMINATED = "TERMINATED"


class TaskState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


VALID_STATE_TRANSITIONS: dict[AgentState, list[AgentState]] = {
    AgentState.CREATED: [AgentState.READY],
    AgentState.READY: [AgentState.QUEUED],
    AgentState.QUEUED: [AgentState.RUNNING, AgentState.FAILED],
    AgentState.RUNNING: [AgentState.WAITING, AgentState.COMPLETED, AgentState.FAILED],
    AgentState.WAITING: [AgentState.RUNNING, AgentState.FAILED],
    AgentState.COMPLETED: [],
    AgentState.FAILED: [AgentState.RETRYING],
    AgentState.RETRYING: [AgentState.RUNNING, AgentState.TERMINATED],
    AgentState.TERMINATED: [],
}


def is_valid_transition(from_state: AgentState | str, to_state: AgentState | str) -> bool:
    try:
        source = from_state if isinstance(from_state, AgentState) else AgentState(from_state)
        target = to_state if isinstance(to_state, AgentState) else AgentState(to_state)
    except ValueError:
        return False

    return target in VALID_STATE_TRANSITIONS.get(source, [])
