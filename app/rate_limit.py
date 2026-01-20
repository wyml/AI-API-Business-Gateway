from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis

from app.config import get_settings

_redis_client: Optional[Redis] = None


async def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def check_rate_limit(key: str, limit: int = 60, window_seconds: int = 60) -> bool:
    """Simple rate limit placeholder using Redis INCR/EXPIRE."""
    redis_client = await get_redis_client()
    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, window_seconds)
    return current <= limit
