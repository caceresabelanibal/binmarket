from __future__ import annotations

import asyncio
import logging
import signal

import redis as redis_sync

from app.lock import EngineLock
from app.tick import run_tick
from binmarket_shared.config import settings
from binmarket_shared.logging_utils import configure_logging
from binmarket_shared.redis_keys import HEARTBEAT_TTL_SECONDS, heartbeat_key

configure_logging("trading-engine")
logger = logging.getLogger("binmarket.trading_engine")


async def main() -> None:
    redis_client = redis_sync.Redis.from_url(settings.redis_url, decode_responses=True)
    lock = EngineLock(redis_client)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)  # type: ignore[attr-defined]
        except (NotImplementedError, AttributeError):
            pass

    logger.info("trading-engine starting (loop interval=%ss)", settings.engine_loop_interval_seconds)

    try:
        while not stop_event.is_set():
            try:
                if await asyncio.to_thread(lock.acquire_or_renew):
                    await asyncio.to_thread(run_tick, redis_client)
                await asyncio.to_thread(redis_client.set, heartbeat_key("trading-engine"), "1", ex=HEARTBEAT_TTL_SECONDS)
            except Exception:
                logger.exception("Unhandled error in trading-engine tick")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.engine_loop_interval_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        await asyncio.to_thread(lock.release)


if __name__ == "__main__":
    asyncio.run(main())
