from __future__ import annotations

import json
import re

from openwebui import call_model
from router import get_model_for_task
from runtime.executor.dag import WorkflowDAG


class PlannerAgent:
    async def plan(self, goal: str, context: dict = {}) -> WorkflowDAG:
        try:
            model_name = get_model_for_task("general")
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a workflow planning agent. Given a goal, output a JSON array "
                        "of tasks. Each task has: id (string), name (string), task_type (one of: "
                        "research, coding, qa, report, general), depends_on (array of task ids). "
                        "Output only valid JSON array, no other text."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Goal: {goal}\nContext: {json.dumps(context)}",
                },
            ]

            response = await call_model(model_name=model_name, messages=messages)
            try:
                content = self._extract_content(response)
                content = self._clean_json_response(content)
                tasks = json.loads(content)
                dag = WorkflowDAG()
                for task in tasks:
                    dag.add_task(
                        task_id=task["id"],
                        name=task["name"],
                        task_type=task["task_type"],
                        depends_on=task.get("depends_on", []),
                    )
                dag.validate()
                return dag
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                return self._build_fallback_dag()
        except Exception:
            return self._build_fallback_dag()

    @staticmethod
    def _extract_content(response: dict) -> str:
        choices = response["choices"]
        message = choices[0]["message"]
        content = message["content"]
        if isinstance(content, list):
            return "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
            )
        if not isinstance(content, str):
            raise ValueError("Planner response content is not a string")
        return content

    @staticmethod
    def _clean_json_response(content: str) -> str:
        # Strip leading/trailing whitespace
        content = content.strip()

        # If it contains ```json, extract content between first ``` and last ```
        if "```json" in content:
            match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()
        # If it starts with ``` (any language), strip that fence
        elif content.startswith("```"):
            match = re.search(r"```[a-z]*\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()

        # Extract just the JSON array using regex
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            return match.group(0)

        return content

    @staticmethod
    def _build_fallback_dag() -> WorkflowDAG:
        dag = WorkflowDAG()
        dag.add_task("t1", "Research", "research", depends_on=[])
        dag.add_task("t2", "Analysis", "general", depends_on=["t1"])
        dag.add_task("t3", "Report", "report", depends_on=["t2"])
        return dag
