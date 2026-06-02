from __future__ import annotations

from typing import Any

from memory.config_loader import get_config


TASK_MODEL_PREFERENCES = {
    "coding": {"qwen3_coder", "phi3"},
    "medical": {"medgemma", "medgemma_15", "medllama2"},
    "research": {"gpt_oss", "qwen25"},
    "qa": {"mistral", "phi35"},
    "report": {"gpt_oss", "qwen25"},
    "embedding": {"nomic"},
    "general": set(),
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _get_models() -> dict[str, dict[str, Any]]:
    config = get_config()
    return config["models"]


def score_model(model_key: str, task_type: str, available_vram_gb: float) -> float:
    models = _get_models()
    model = models[model_key]
    capabilities = model.get("capabilities", [])
    preferred_models = TASK_MODEL_PREFERENCES.get(task_type, set())

    if task_type == "general":
        capability_score = 1.0
    elif model_key in preferred_models or task_type in capabilities:
        capability_score = 1.0
    else:
        capability_score = 0.3

    latency_ms = float(model.get("latency_ms", 3000))
    latency_score = _clamp(1.0 - (latency_ms / 3000.0))
    memory_score = 1.0 if float(model.get("vram_gb", 0.0)) <= available_vram_gb else 0.0
    load_score = 0.8

    total_score = (
        capability_score * 0.5
        + latency_score * 0.2
        + memory_score * 0.2
        + load_score * 0.1
    )
    return _clamp(total_score)
