from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

from memory.qdrant.client import QdrantClient
from observability import LangfuseLogger, trace_operation
from openwebui.client import call_model
from router.benchmarks.benchmark_store import save_metric


class BaseAgent(ABC):
    def __init__(self, agent_id: str, model_name: str, token_manager) -> None:
        self.agent_id = agent_id
        self.model_name = model_name
        self.token_manager = token_manager
        self.qdrant_client = QdrantClient()
        self.langfuse_logger = LangfuseLogger()

    @abstractmethod
    async def run(self, task_input: str, context: dict | None = None) -> dict:
        raise NotImplementedError

    async def _call_llm(self, messages: list[dict], task_type: str) -> str:
        start_time = time.perf_counter()

        try:
            with trace_operation("llm_call", {"model": self.model_name}):
                response = await call_model(
                    model_name=self.model_name,
                    messages=messages,
                )

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            content = self._extract_content(response)
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            total_tokens = int(usage.get("total_tokens", 0) or 0)

            await save_metric(
                self.model_name,
                task_type,
                latency_ms,
                total_tokens,
                True,
                False,
            )
            await self.langfuse_logger.log_trace(
                workflow_id=getattr(self, "workflow_id", self.agent_id),
                task_type=task_type,
                model=self.model_name,
                prompt=json.dumps(messages),
                response=content,
                latency_ms=latency_ms,
                success=True,
            )
            return content
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            await save_metric(
                self.model_name,
                task_type,
                latency_ms,
                0,
                False,
                False,
            )
            await self.langfuse_logger.log_trace(
                workflow_id=getattr(self, "workflow_id", self.agent_id),
                task_type=task_type,
                model=self.model_name,
                prompt=json.dumps(messages),
                response=str(exc),
                latency_ms=latency_ms,
                success=False,
            )
            raise

    async def _save_to_memory(self, content: str, collection: str = "arp_knowledge") -> None:
        embedding = [0.0] * 768
        payload = {"content": content, "agent_id": self.agent_id}
        self.qdrant_client.upsert(
            collection=collection,
            id=f"{self.agent_id}_{int(time.time() * 1000)}",
            vector=embedding,
            payload=payload,
        )

    async def _search_memory(self, query: str, collection: str = "arp_knowledge") -> list[dict]:
        del query
        query_vector = [0.0] * 768
        results = self.qdrant_client.search(
            collection=collection,
            vector=query_vector,
            limit=5,
        )
        return [hit.payload for hit in results]

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        choices = response.get("choices", [])
        if not choices:
            return ""

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            return "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
            )
        if isinstance(content, str):
            return content
        return str(content)
