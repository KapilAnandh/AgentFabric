from __future__ import annotations

import asyncio
import time


class QueueManager:
    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()

    async def enqueue(self, agent_id, priority=5, task_type="general") -> None:
        timestamp = time.time()
        await self._queue.put((priority, timestamp, str(agent_id), task_type))

    async def dequeue(self) -> dict | None:
        if self._queue.empty():
            return None

        priority, _timestamp, agent_id, task_type = await self._queue.get()
        return {
            "agent_id": agent_id,
            "task_type": task_type,
            "priority": priority,
        }

    def queue_size(self) -> int:
        return self._queue.qsize()

    def get_queue_snapshot(self) -> list[dict]:
        snapshot = []
        for priority, timestamp, agent_id, task_type in sorted(list(self._queue._queue)):
            snapshot.append(
                {
                    "agent_id": agent_id,
                    "task_type": task_type,
                    "priority": priority,
                    "timestamp": timestamp,
                }
            )
        return snapshot
