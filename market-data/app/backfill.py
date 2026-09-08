"""Historical data backfill worker (section 7 of the spec).

Consumes jobs pushed by the backend onto the `BACKFILL_QUEUE_KEY` Redis list.
Never re-downloads candles it already has, but — unlike a naive "resume from
the last candle" — it also fills a gap *before* the earliest candle we have.
That gap is real: a symbol just picked by auto-selection starts getting live
candles from the WebSocket the moment it's selected, often seconds before its
historical backfill job even runs. A "resume forward from the latest candle"
job would see that live-streamed candle, conclude "already caught up to
now", and skip fetching any real history at all — which is exactly what
happened the first time this ran live. Computing both gaps explicitly avoids
that regardless of which one shows up first.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import func, select
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


def _existing_range_ms(db, symbol: str, timeframe: str) -> tuple[int | None, int | None]:
    earliest, latest = db.execute(
        select(func.min(Candle.open_time), func.max(Candle.open_time))
        .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
    ).one()
    return (_ms(earliest) if earliest else None), (_ms(latest) if latest else None)


def _ranges_to_fetch(db, symbol: str, timeframe: str, requested_start: datetime | None, requested_end_ms: int) -> list[tuple[int, int]]:
    start_ms = _ms(requested_start) if requested_start else _ms(datetime(2020, 1, 1, tzinfo=timezone.utc))
    earliest_ms, latest_ms = _existing_range_ms(db, symbol, timeframe)

    if earliest_ms is None:
        return [(start_ms, requested_end_ms)]

    ranges = []
    if start_ms < earliest_ms:
        ranges.append((start_ms, earliest_ms))  # backward: fill history older than what we have
    if requested_end_ms > latest_ms:
        ranges.append((latest_ms + 1, requested_end_ms))  # forward: catch up to the requested end
    return ranges


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
    # The job is looked up on a separate DB connection from whatever created
    # it; a short retry covers the (now much rarer, but not impossible)
    # window where this runs before that transaction's commit is visible
    # here, instead of silently discarding a real, just-enqueued job.
    for attempt in range(3):
        with session_scope() as db:
            job = db.get(SyncJob, job_id)
            if job is not None:
                job.status = SyncStatus.RUNNING
                break
        if attempt < 2:
            time.sleep(0.5)
    else:
        logger.warning("Backfill job %s (%s/%s) not found in DB after retries — dropping", job_id, symbol, timeframe)
        return

    client = BinanceClient("", "", environment="production")  # public klines endpoint, no key needed
    total_synced = 0
    try:
        end_ms = _ms(end) if end else _ms(datetime.now(timezone.utc))
        with session_scope() as db:
            ranges = _ranges_to_fetch(db, symbol, timeframe, start, end_ms)

        for range_start_ms, range_end_ms in ranges:
            cursor_ms = range_start_ms
            while cursor_ms < range_end_ms:
                klines = client.get_klines(symbol, timeframe, cursor_ms, range_end_ms, limit=PAGE_LIMIT)
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
