"""Fills in a HistoricalEvent's missing `market_move_5d_pct` once enough
real trading days have genuinely passed - never estimates or guesses in the
meantime (see events_seed.py's Tesla Roadster entry for why this exists:
it was seeded 2 trading days after the event, before a real 5-day close
could possibly exist).

This is how the historical-events table "grows" on its own, as the user
asked about - not by inventing new events automatically (that would risk
polluting a curated, hand-verified table with noise; adding a genuinely new
event is still a deliberate edit to events_seed.py), but by completing the
real numbers for events already in it as time actually passes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import HistoricalEvent
from .prices import fetch_daily_closes

logger = logging.getLogger("marketpulse.events_backfill")

# 9 calendar days comfortably covers 5 US trading days even across a
# 3-day weekend plus one market holiday - short enough to not guess, long
# enough that the real data should exist by then.
MIN_DAYS_BEFORE_ATTEMPTING = 9


def backfill_pending_event_moves(db: Session) -> int:
    pending = (
        db.query(HistoricalEvent)
        .filter(HistoricalEvent.market_move_5d_pct.is_(None), HistoricalEvent.symbol.isnot(None))
        .all()
    )
    now = datetime.now(timezone.utc)
    updated = 0

    for event in pending:
        event_date = event.event_date if event.event_date.tzinfo else event.event_date.replace(tzinfo=timezone.utc)
        if (now - event_date).days < MIN_DAYS_BEFORE_ATTEMPTING:
            continue

        closes = fetch_daily_closes(event.symbol, days_back=25)
        if not closes:
            continue  # source temporarily unavailable - retry next cycle, never guess

        idx = None
        for i, (d, _) in enumerate(closes):
            if datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) >= event_date:
                idx = i
                break
        if idx is None or idx == 0 or idx + 5 >= len(closes):
            continue  # don't have the real window yet - retry next cycle

        prev_close = closes[idx - 1][1]
        day5_close = closes[idx + 5][1]
        move_5d_pct = round((day5_close - prev_close) / prev_close * 100, 2)

        event.market_move_5d_pct = move_5d_pct
        event.source_note = (
            event.source_note
            + f" [Backfilled {now.date().isoformat()}: 5-trading-day close "
            f"{closes[idx + 5][0].isoformat()} = {day5_close:.2f} -> {move_5d_pct:+.2f}% vs. the "
            f"pre-event base, computed from real Yahoo Finance daily closes.]"
        )
        updated += 1
        logger.info("Backfilled 5-day move for '%s': %+.2f%%", event.title, move_5d_pct)

    if updated:
        db.commit()
    return updated
