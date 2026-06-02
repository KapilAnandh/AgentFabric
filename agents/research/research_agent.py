from agents.base_agent import BaseAgent


class ResearchAgent(BaseAgent):
    """Agent specialized in research and information analysis."""

    async def run(self, task_input: str, context: dict = {}) -> dict:
        """Execute research task."""
        messages = [
            {
                "role": "system",
                "content": "You are a research agent. Analyse the topic thoroughly, find key facts, summarise findings clearly."
            },
            {
                "role": "user",
                "content": task_input
            }
        ]

        content = await self._call_llm(messages, task_type="research")

        # Save result to memory
        await self._save_to_memory(content)

        return {
            "type": "research",
            "result": content,
            "agent_id": self.agent_id
        }
