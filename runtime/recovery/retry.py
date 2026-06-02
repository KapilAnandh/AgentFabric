from __future__ import annotations

import asyncio


class RetryController:
    """Controls retry logic for failed agent tasks."""

    def __init__(self, max_retries: int = 3, backoff_seconds: int = 5) -> None:
        """
        Initialize retry controller.

        Args:
            max_retries: Maximum number of retry attempts
            backoff_seconds: Base backoff duration in seconds
        """
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    async def should_retry(self, agent_id: str, lifecycle_manager) -> bool:
        """
        Check if an agent should be retried.

        Args:
            agent_id: Agent identifier
            lifecycle_manager: AgentLifecycleManager instance

        Returns:
            True if retry count < max_retries, False otherwise
        """
        agent = await lifecycle_manager.get_agent(agent_id)
        if agent is None:
            return False

        return agent.retry_count < self.max_retries

    async def increment_retry(self, agent_id: str, lifecycle_manager) -> None:
        """
        Increment retry count and transition agent to RETRYING state.

        Args:
            agent_id: Agent identifier
            lifecycle_manager: AgentLifecycleManager instance
        """
        from runtime.lifecycle.states import AgentState

        agent = await lifecycle_manager.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")

        # Increment retry count
        agent.retry_count += 1

        # Transition to RETRYING state
        await lifecycle_manager.transition(agent_id, AgentState.RETRYING)

    async def wait_before_retry(self, attempt: int) -> None:
        """
        Wait with exponential backoff before retrying.

        Args:
            attempt: Current retry attempt number (1-indexed)
        """
        delay = self.backoff_seconds * attempt
        await asyncio.sleep(delay)
