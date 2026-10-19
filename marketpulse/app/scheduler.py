"""Background loop, run as an asyncio task inside the single app process
(no separate worker container - see the Dockerfile/compose comments for
why one container is deliberate here). Every `ingest_interval_minutes`:
fetch feeds, refresh the price cache, recompute and store a fresh
prediction snapshot.
"""
from __future__ import annotations

import asyncio
import logging

from .config import settings
from .db import session_scope
from .ingest import ingest_all_feeds, refresh_price_cache
from .predictor import generate_prediction, persist_prediction

logger = logging.getLogger("marketpulse.scheduler")


def run_cycle_once() -> None:
    with session_scope() as db:
        inserted = ingest_all_feeds(db)
        logger.info("Ingested %d new articles", inserted)

    with session_scope() as db:
        refresh_price_cache(db, settings.primary_symbol)

    with session_scope() as db:
        result = generate_prediction(db, settings.primary_symbol)
        prediction = persist_prediction(db, settings.primary_symbol, 48, result)
        logger.info(
            "New prediction for %s: %s (confidence %.1f%%, %d articles)",
            settings.primary_symbol, prediction.direction, prediction.confidence_pct, result.article_count,
        )


async def run_forever(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(run_cycle_once)
        except Exception:
            logger.exception("Scheduler cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.ingest_interval_minutes * 60)
        except asyncio.TimeoutError:
            pass
