from __future__ import annotations

from memory.config_loader import get_config


class GPUManager:
    def __init__(self) -> None:
        config = get_config()
        gpu_config = config["gpu"]
        self.total_vram_gb = float(gpu_config["total_vram_gb"])
        self.reserved_gb = float(gpu_config["reserved_gb"])
        self.available_vram = self.total_vram_gb - self.reserved_gb
        self._models = config["models"]
        self._allocations: dict[str, float] = {}

    async def allocate(self, agent_id, model_key) -> bool:
        model_vram = float(self._models[model_key]["vram_gb"])
        used_vram = sum(self._allocations.values())
        if used_vram + model_vram > self.available_vram:
            return False

        self._allocations[str(agent_id)] = model_vram
        return True

    async def release(self, agent_id) -> float:
        return float(self._allocations.pop(str(agent_id), 0.0))

    def get_available_vram(self) -> float:
        return self.available_vram - sum(self._allocations.values())

    def get_status(self) -> dict:
        used_vram = sum(self._allocations.values())
        return {
            "total": self.total_vram_gb,
            "available": self.get_available_vram(),
            "used": used_vram,
            "allocations": dict(self._allocations),
        }
