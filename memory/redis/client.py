from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from ..config_loader import get_config


class RedisClient:
    def __init__(self) -> None:
        config = get_config()
        redis_url = config["memory"]["redis_url"]
        self._client = Redis.from_url(redis_url, decode_responses=True)

    async def set_state(self, key: str, value: Any, ttl: int = 3600) -> bool:
        payload = json.dumps(value)
        return bool(await self._client.set(name=key, value=payload, ex=ttl))

    async def get_state(self, key: str) -> Any:
        value = await self._client.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def delete_state(self, key: str) -> int:
        return int(await self._client.delete(key))

    async def publish(self, channel: str, message: Any) -> int:
        payload = json.dumps(message)
        return int(await self._client.publish(channel, payload))

    async def subscribe(self, channel: str):
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub
