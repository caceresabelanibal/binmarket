"""Historical data backfill worker (section 7 of the spec).

Consumes jobs pushed by the backend onto the `BACKFILL_QUEUE_KEY` Redis list.
Never re-downloads candles it already has: if the job doesn't specify an
explicit start, it resumes from the last candle already stored for that
symbol/timeframe (incremental sync). Paginates Binance's 1000-candle-per-call
limit until it reaches the requested end (or the present).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import Candle, SyncJob, SyncStatus
from binmarket_shared.redis_keys import BACKFILL_QUEUE_KEY

logger = logging.getLogger("binmarket.market_data.backfill")

PAGE_LIMIT = 1000
RATE_LIMIT_PAUSE_SECONDS = 0.3


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _resume_start_ms(symbol: str, timeframe: str, requested_start: datetime | None) -> int:
    with session_scope() as db:
        last = db.execute(
            select(Candle.open_time)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(Candle.open_time.desc())
            .limit(1)
        ).scalar_one_or_none()
    if last is not None:
        return _ms(last) + 1
    if requested_start is not None:
        return _ms(requested_start)
    return _ms(datetime(2020, 1, 1, tzinfo=timezone.utc))


def _upsert_batch(symbol: str, timeframe: str, klines: list[list]) -> None:
    now_ms = _ms(datetime.now(timezone.utc))
    with session_scope() as db:
        for k in klines:
            open_ms, close_ms = k[0], k[6]
            values = dict(
                symbol=symbol, timeframe=timeframe,
                open_time=datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc),
                close_time=datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc),
                open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                quote_volume=float(k[7]), trades_count=int(k[8]), is_closed=close_ms < now_ms,
            )
            stmt = pg_insert(Candle).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "timeframe", "open_time"],
                set_={key: v for key, v in values.items() if key not in ("symbol", "timeframe", "open_time")},
            )
            db.execute(stmt)


def _run_job_sync(job_id: str, symbol: str, timeframe: str, start: datetime | None, end: datetime | None, environment: str) -> None:
    with session_scope() as db:
        job = db.get(SyncJob, job_id)
        if job is None:
            return
        job.status = SyncStatus.RUNNING

    client = BinanceClient("", "", environment="production")  # public klines endpoint, no key needed
    total_synced = 0
    try:
        cursor_ms = _resume_start_ms(symbol, timeframe, start)
        end_ms = _ms(end) if end else _ms(datetime.now(timezone.utc))

        while cursor_ms < end_ms:
            klines = client.get_klines(symbol, timeframe, cursor_ms, end_ms, limit=PAGE_LIMIT)
            if not klines:
                break
            _upsert_batch(symbol, timeframe, klines)
            total_synced += len(klines)
            cursor_ms = klines[-1][0] + 1

            with session_scope() as db:
                job = db.get(SyncJob, job_id)
                if job is not None:
                    job.candles_synced = total_synced
                    job.last_synced_open_time = datetime.fromtimestamp(klines[-1][0] / 1000, tz=timezone.utc)

            if len(klines) < PAGE_LIMIT:
                break
            import time

            time.sleep(RATE_LIMIT_PAUSE_SECONDS)

        with session_scope() as db:
            job = db.get(SyncJob, job_id)
            if job is not None:
                job.status = SyncStatus.DONE
        logger.info("Backfill job %s done: %d candles synced for %s/%s", job_id, total_synced, symbol, timeframe)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Backfill job %s failed", job_id)
        with session_scope() as db:
            job = db.get(SyncJob, job_id)
            if job is not None:
                job.status = SyncStatus.FAILED
                job.error_message = str(exc)
    finally:
        client.close()


async def run_backfill_worker(redis, environment: str, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        raw = await redis.blpop(BACKFILL_QUEUE_KEY, timeout=5)
        if raw is None:
            continue
        _, payload = raw
        job = json.loads(payload)
        start = datetime.fromisoformat(job["start"]) if job.get("start") else None
        end = datetime.fromisoformat(job["end"]) if job.get("end") else None
        await asyncio.to_thread(_run_job_sync, job["job_id"], job["symbol"], job["timeframe"], start, end, environment)
