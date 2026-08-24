from __future__ import annotations

import asyncio
import logging
import signal

import redis.asyncio as redis_async

from app.backfill import run_backfill_worker
from app.ingest import run_ingestion
from binmarket_shared.config import settings
from binmarket_shared.logging_utils import configure_logging
from binmarket_shared.redis_keys import HEARTBEAT_TTL_SECONDS, heartbeat_key

configure_logging("market-data")
logger = logging.getLogger("binmarket.market_data")


async def heartbeat_loop(redis, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await redis.set(heartbeat_key("market-data"), "1", ex=HEARTBEAT_TTL_SECONDS)
        await asyncio.sleep(HEARTBEAT_TTL_SECONDS / 3)


async def main() -> None:
    redis = redis_async.Redis.from_url(settings.redis_url, decode_responses=True)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)  # type: ignore[attr-defined]
        except (NotImplementedError, AttributeError):
            pass

    logger.info("market-data starting (binance_environment=%s for backfill)", settings.binance_environment)

    await asyncio.gather(
        heartbeat_loop(redis, stop_event),
        run_ingestion(redis, "production", stop_event),
        run_backfill_worker(redis, settings.binance_environment, stop_event),
    )


if __name__ == "__main__":
    asyncio.run(main())
