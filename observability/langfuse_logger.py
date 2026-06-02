from __future__ import annotations

import contextlib

import httpx

from memory.config_loader import get_config


class LangfuseLogger:
    def __init__(self) -> None:
        config = get_config()
        self.langfuse_url = config["observability"]["langfuse_url"].rstrip("/")

    async def log_trace(self, workflow_id, task_type, model, prompt, response, latency_ms, success):
        payload = {
            "workflow_id": workflow_id,
            "task_type": task_type,
            "model": model,
            "prompt": prompt,
            "response": response,
            "latency_ms": latency_ms,
            "success": success,
        }
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self.langfuse_url}/api/public/traces", json=payload)

    async def log_score(self, trace_id, name, value):
        payload = {
            "trace_id": trace_id,
            "name": name,
            "value": value,
        }
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self.langfuse_url}/api/public/scores", json=payload)
