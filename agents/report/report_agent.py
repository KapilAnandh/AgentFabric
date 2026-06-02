from agents.base_agent import BaseAgent


class ReportAgent(BaseAgent):
    """Agent specialized in generating professional reports and documentation."""

    async def run(self, task_input: str, context: dict = {}) -> dict:
        """Execute report generation task."""
        messages = [
            {
                "role": "system",
                "content": "You are a report generation agent. Create a well-structured, professional report from the provided information."
            },
            {
                "role": "user",
                "content": task_input
            }
        ]

        content = await self._call_llm(messages, task_type="report")

        # Save result to memory
        await self._save_to_memory(content)

        return {
            "type": "report",
            "result": content,
            "agent_id": self.agent_id
        }
