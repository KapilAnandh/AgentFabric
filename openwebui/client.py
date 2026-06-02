from __future__ import annotations

import logging
from typing import Any

import httpx

from memory.config_loader import get_config


logger = logging.getLogger(__name__)


async def call_model(
    model_name: str,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int = 1000,
) -> dict[str, Any]:
    config = get_config()
    llm_config = config["llm"]
    base_url = llm_config["openwebui_base_url"].rstrip("/")
    api_key = llm_config["openwebui_api_key"]
    timeout = llm_config["timeout"]
    request_temperature = llm_config["temperature"] if temperature is None else temperature

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": request_temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/api/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException as exc:
        logger.warning("OpenWebUI request timed out for model %s: %s", model_name, exc)
    except httpx.HTTPError as exc:
        logger.warning("OpenWebUI request failed for model %s: %s", model_name, exc)

    return {}


async def test_connection() -> bool:
    config = get_config()
    medgemma_model = config["models"]["medgemma"]["name"]
    result = await call_model(
        model_name=medgemma_model,
        messages=[{"role": "user", "content": "hello"}],
    )
    return bool(result)
