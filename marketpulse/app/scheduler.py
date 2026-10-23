"""Background loop, run as an asyncio task inside the single app process
(no separate worker container - see the Dockerfile/compose comments for
why one container is deliberate here). Every `ingest_interval_minutes`:
fetch feeds, refresh the price cache, recompute and store a fresh
prediction snapshot - one per real ticker currently in the news, not just
the one configured primary symbol (see predictor.py's
generate_all_predictions).
"""
from __future__ import annotations

import asyncio
import logging

from .config import settings
from .db import session_scope
from .events_backfill import backfill_pending_event_moves
from .ingest import ingest_all_feeds, prune_old_data, refresh_price_cache
from .learning import update_weights_if_due
from .predictor import PREDICTION_HORIZON_HOURS, generate_all_predictions, persist_prediction

logger = logging.getLogger("marketpulse.scheduler")


def run_cycle_once() -> None:
    with session_scope() as db:
        inserted = ingest_all_feeds(db)
        logger.info("Ingested %d new articles", inserted)

    with session_scope() as db:
        pruned_articles, pruned_predictions = prune_old_data(db)
        if pruned_articles or pruned_predictions:
            logger.info("Pruned %d old articles, %d old predictions", pruned_articles, pruned_predictions)

    with session_scope() as db:
        backfilled = backfill_pending_event_moves(db)
        if backfilled:
            logger.info("Backfilled %d historical event 5-day move(s) with real data", backfilled)

    with session_scope() as db:
        adjustment = update_weights_if_due(db)
        if adjustment:
            logger.info("Adjusted model weights (sample size %d): %s", adjustment.sample_size, adjustment.note)

    with session_scope() as db:
        results = generate_all_predictions(db)

    # Refresh the price cache for every ticker that got a prediction this
    # cycle, not just the primary symbol - the backtest can only ever score
    # a ticker it has a real cached close for.
    with session_scope() as db:
        for symbol in results:
            refresh_price_cache(db, symbol)

    with session_scope() as db:
        for symbol, result in results.items():
            prediction = persist_prediction(db, symbol, PREDICTION_HORIZON_HOURS, result)
            logger.info(
                "New prediction for %s: %s (confidence %.1f%%, %d articles)",
                symbol, prediction.direction, prediction.confidence_pct, result.article_count,
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
