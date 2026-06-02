from __future__ import annotations

from memory.config_loader import get_config


class TokenBudgetManager:
    def __init__(self) -> None:
        config = get_config()
        memory_config = config["memory"]
        self.token_budget_default = int(memory_config["token_budget_default"])
        self.token_budget_max = int(memory_config["token_budget_max"])
        self._budgets: dict[str, dict[str, int]] = {}

    def allocate_budget(self, agent_id, requested=None) -> int:
        requested_amount = self.token_budget_default if requested is None else int(requested)
        allocated_amount = min(requested_amount, self.token_budget_max)
        self._budgets[str(agent_id)] = {"budget": allocated_amount, "used": 0}
        return allocated_amount

    def consume(self, agent_id, tokens: int) -> bool:
        entry = self._budgets.get(str(agent_id))
        if entry is None:
            return False

        entry["used"] += int(tokens)
        return entry["used"] <= entry["budget"]

    def get_remaining(self, agent_id) -> int:
        entry = self._budgets.get(str(agent_id))
        if entry is None:
            return 0
        return max(entry["budget"] - entry["used"], 0)

    def release(self, agent_id) -> None:
        self._budgets.pop(str(agent_id), None)
