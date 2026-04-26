import json
from typing import Any

import redis.asyncio as redis

from .config import REDIS_URL


redis_client = redis.from_url(REDIS_URL, decode_responses=True)


async def cache_get_json(key: str) -> dict[str, Any] | None:
    try:
        raw = await redis_client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        # Fail open when Redis is unavailable so API endpoints still work locally.
        return None


async def cache_set_json(key: str, payload: dict[str, Any], ttl_seconds: int = 300) -> None:
    try:
        await redis_client.setex(key, ttl_seconds, json.dumps(payload))
    except Exception:
        # Ignore cache write failures in local/dev environments.
        return None
