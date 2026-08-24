"""Distributed lock (section 5 of the spec): guarantees at most one
trading-engine instance runs the analysis/execution loop at a time, even if
the service were ever accidentally scaled or run twice against the same
database. A single docker-compose deployment only ever runs one replica of
this service by design — this lock is the defensive backstop, not the
primary safeguard.
"""
from __future__ import annotations

import logging
import uuid

from binmarket_shared.redis_keys import ENGINE_LOCK_KEY, ENGINE_LOCK_TTL_SECONDS

logger = logging.getLogger("binmarket.trading_engine.lock")


class EngineLock:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.token = str(uuid.uuid4())

    def acquire_or_renew(self) -> bool:
        acquired = self.redis.set(ENGINE_LOCK_KEY, self.token, nx=True, ex=ENGINE_LOCK_TTL_SECONDS)
        if acquired:
            return True

        current = self.redis.get(ENGINE_LOCK_KEY)
        if current == self.token:
            self.redis.set(ENGINE_LOCK_KEY, self.token, ex=ENGINE_LOCK_TTL_SECONDS)
            return True

        logger.warning("Another trading-engine instance holds the lock; skipping this tick")
        return False

    def release(self) -> None:
        if self.redis.get(ENGINE_LOCK_KEY) == self.token:
            self.redis.delete(ENGINE_LOCK_KEY)
