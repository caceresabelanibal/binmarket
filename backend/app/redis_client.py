from __future__ import annotations

import redis as redis_sync
import redis.asyncio as redis_async

from binmarket_shared.config import settings

redis_client = redis_sync.Redis.from_url(settings.redis_url, decode_responses=True)


def get_async_redis() -> redis_async.Redis:
    return redis_async.Redis.from_url(settings.redis_url, decode_responses=True)
