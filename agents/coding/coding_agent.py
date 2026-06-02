from agents.base_agent import BaseAgent


class CodingAgent(BaseAgent):
    """Agent specialized in code generation and programming tasks."""

    async def run(self, task_input: str, context: dict = {}) -> dict:
        """Execute coding task."""
        messages = [
            {
                "role": "system",
                "content": "You are a coding agent. Write clean, working Python code with clear comments. Return only the code."
            },
            {
                "role": "user",
                "content": task_input
            }
        ]

        content = await self._call_llm(messages, task_type="coding")

        # Save result to memory
        await self._save_to_memory(content)

        return {
            "type": "coding",
            "result": content,
            "language": "python",
            "agent_id": self.agent_id
        }
