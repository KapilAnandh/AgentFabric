from __future__ import annotations

from memory.config_loader import get_config

from .gpu_manager import GPUManager
from .queue_manager import QueueManager
from .token_manager import TokenBudgetManager


class ResourceManager:
    def __init__(self) -> None:
        self.config = get_config()
        self.gpu_manager = GPUManager()
        self.token_manager = TokenBudgetManager()
        self.queue_manager = QueueManager()

    async def request_resources(self, agent_id, model_key, task_type, token_budget=None) -> dict:
        allocated = await self.gpu_manager.allocate(agent_id, model_key)
        if not allocated:
            await self.queue_manager.enqueue(agent_id=agent_id, task_type=task_type)
            return {"status": "queued"}

        allocated_budget = self.token_manager.allocate_budget(agent_id, requested=token_budget)
        vram_allocated = float(self.config["models"][model_key]["vram_gb"])
        return {
            "status": "allocated",
            "vram_allocated": vram_allocated,
            "token_budget": allocated_budget,
        }

    async def release_resources(self, agent_id) -> None:
        await self.gpu_manager.release(agent_id)
        self.token_manager.release(agent_id)

    def get_system_status(self) -> dict:
        gpu_status = self.gpu_manager.get_status()
        return {
            "gpu": gpu_status,
            "queue_size": self.queue_manager.queue_size(),
            "active_agents_count": len(gpu_status["allocations"]),
        }
