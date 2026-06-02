from agents.base_agent import BaseAgent


class VisionAgent(BaseAgent):
    """Agent specialized in visual content analysis and description."""

    async def run(self, task_input: str, context: dict = {}) -> dict:
        """Execute vision analysis task."""
        messages = [
            {
                "role": "system",
                "content": "You are a vision analysis agent. Describe and analyse visual content in detail."
            },
            {
                "role": "user",
                "content": task_input
            }
        ]

        content = await self._call_llm(messages, task_type="general")

        return {
            "type": "vision",
            "result": content,
            "agent_id": self.agent_id
        }
