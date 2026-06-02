from __future__ import annotations

from memory.config_loader import get_config

from .scorer import score_model


def select_model(task_type: str, available_vram_gb: float = 22.0) -> tuple[str, str]:
    models = get_config()["models"]
    best_key = ""
    best_name = ""
    best_score = -1.0

    for model_key, model_config in models.items():
        current_score = score_model(model_key, task_type, available_vram_gb)
        if current_score > best_score:
            best_key = model_key
            best_name = model_config["name"]
            best_score = current_score

    if best_score < 0.1:
        return ("mistral", "mistral:7b-instruct")

    return (best_key, best_name)


def get_model_for_task(task_type: str) -> str:
    _, model_name = select_model(task_type)
    return model_name
