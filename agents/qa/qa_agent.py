from agents.base_agent import BaseAgent


class QAAgent(BaseAgent):
    """Agent specialized in quality assurance and code review."""

    async def run(self, task_input: str, context: dict = {}) -> dict:
        """Execute QA task."""
        messages = [
            {
                "role": "system",
                "content": "You are a QA agent. Review the provided work for correctness, completeness, and quality. List any issues found."
            },
            {
                "role": "user",
                "content": task_input
            }
        ]

        content = await self._call_llm(messages, task_type="qa")

        # Determine if QA passed based on response
        passed = "no issues" in content.lower()

        return {
            "type": "qa",
            "result": content,
            "passed": passed,
            "agent_id": self.agent_id
        }
