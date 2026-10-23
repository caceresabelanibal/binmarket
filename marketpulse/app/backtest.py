"""Scores past predictions against what actually happened - the honesty
check the user explicitly asked for: does this thing call the direction
right, or not? A prediction only has a verdict once its horizon has
actually elapsed; a same-day prediction made this afternoon has no verdict
yet and is reported as PENDING, never guessed at.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import MarketPriceDaily, Prediction


@dataclass
class PredictionVerdict:
    prediction_id: str
    symbol: str
    created_at: str
    direction: str
    confidence_pct: float
    price_at_prediction: float | None
    price_at_horizon: float | None
    actual_move_pct: float | None
    verdict: str  # "CORRECT" | "WRONG" | "PENDING" | "NO_TRADE" | "NO_DATA"


def _price_as_of(prices: list[MarketPriceDaily], target: datetime, max_lookback_days: int = 7) -> MarketPriceDaily | None:
    """The most recent cached close that had ALREADY happened by `target` -
    never one that postdates it. Real bug this replaced: the previous
    version picked whichever cached close was NEAREST to `target` in
    absolute time, which for a prediction made in the afternoon/evening
    often meant the NEXT day's close (closer in clock-hours than
    yesterday's) got used as the "entry" price - a close that didn't exist
    yet when the prediction was actually made. That same next-day close
    then also became the nearest match for the HORIZON side a day later,
    so entry and horizon frequently collided on the identical row, forcing
    an artificial 0.00% "move" (see the PENDING guard below). As-of
    (backward-only) lookup can't do that: the horizon's cutoff is always
    later than the entry's, so it can only match an equal-or-later close.
    `max_lookback_days` guards against silently using a wildly stale close
    if a ticker's price cache has a real gap (weekends/holidays need at
    most a few days, never this many)."""
    candidates = [p for p in prices if p.price_date <= target and (target - p.price_date).days <= max_lookback_days]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.price_date)


def evaluate_predictions(
    db: Session,
    symbol: str | None = None,
    days_back: int = 14,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[PredictionVerdict]:
    """Real production bug this replaced: predictions are generated every
    `ingest_interval_minutes` (30 by default) and need `horizon_hours` (48 at
    the time this bug existed, now predictor.PREDICTION_HORIZON_HOURS - see
    that module for why it was shortened to 24) to actually elapse before
    they can be scored - but the old `limit(60)` (a row count, not a time
    window) only ever reached back ~30 hours (60 * 30min), always LESS than
    the horizon. The backtest could never show a single CORRECT/WRONG
    verdict, no matter how long the service ran - every prediction was
    perpetually "too recent" by construction. A real time window fixes this
    structurally. Each row's OWN `horizon_hours` always decides its verdict
    timing here, never a module-level constant re-read at evaluation time -
    so predictions made under an older horizon setting keep evaluating
    against the value they were actually created with, unless explicitly
    migrated (see app/seed.py's migrate_prediction_horizon).

    `symbol=None` evaluates every ticker that has predictions (requested
    directly by the user - MarketPulse now tracks whatever real tickers the
    news actually names, not just one configured index), each scored
    against its OWN cached price history. `symbol` does a case-insensitive
    SUBSTRING match (not exact), matching the "buscar por ticker" the user
    asked for in the dashboard filter. `date_from`/`date_to` override the
    `days_back` default when given, so a deliberate date-range search isn't
    silently capped at 14 days - with 40+ tickers at a 30-min cadence this
    table grows fast, so filtering happens in SQL, not after pulling
    everything into Python.
    """
    query = db.query(Prediction)
    if date_from is not None:
        query = query.filter(Prediction.created_at >= date_from)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        query = query.filter(Prediction.created_at >= cutoff)
    if date_to is not None:
        query = query.filter(Prediction.created_at < date_to)
    if symbol is not None:
        query = query.filter(Prediction.symbol.ilike(f"%{symbol}%"))
    predictions = query.order_by(Prediction.created_at.desc()).all()
    if not predictions:
        return []

    matched_symbols = {p.symbol for p in predictions}
    all_prices = db.query(MarketPriceDaily).filter(MarketPriceDaily.symbol.in_(matched_symbols)).all()
    prices_by_symbol: dict[str, list[MarketPriceDaily]] = {}
    for p in all_prices:
        prices_by_symbol.setdefault(p.symbol, []).append(p)

    now = datetime.now(timezone.utc)
    verdicts: list[PredictionVerdict] = []
    for p in predictions:
        prices = prices_by_symbol.get(p.symbol, [])
        created_at = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=timezone.utc)
        horizon_time = created_at + timedelta(hours=p.horizon_hours)

        entry_price_row = _price_as_of(prices, created_at)
        entry_price = entry_price_row.close if entry_price_row else None

        if p.direction == "NO_TRADE":
            verdicts.append(PredictionVerdict(
                p.id, p.symbol, created_at.isoformat(), p.direction, p.confidence_pct,
                entry_price, None, None, "NO_TRADE",
            ))
            continue

        if now < horizon_time:
            verdicts.append(PredictionVerdict(
                p.id, p.symbol, created_at.isoformat(), p.direction, p.confidence_pct,
                entry_price, None, None, "PENDING",
            ))
            continue

        horizon_price_row = _price_as_of(prices, horizon_time)
        if not entry_price_row or not horizon_price_row:
            verdicts.append(PredictionVerdict(
                p.id, p.symbol, created_at.isoformat(), p.direction, p.confidence_pct,
                entry_price, horizon_price_row.close if horizon_price_row else None, None, "NO_DATA",
            ))
            continue

        # With as-of (backward-only) lookups this can only happen when no
        # new close has posted ANYWHERE between created_at and horizon_time
        # yet - a real "the data just isn't there yet" wait, not an
        # artifact of the matching method. Scored as PENDING, never as a
        # fabricated 0.00% move.
        if horizon_price_row.price_date <= entry_price_row.price_date:
            verdicts.append(PredictionVerdict(
                p.id, p.symbol, created_at.isoformat(), p.direction, p.confidence_pct,
                entry_price_row.close, horizon_price_row.close, None, "PENDING",
            ))
            continue

        actual_move_pct = (horizon_price_row.close - entry_price_row.close) / entry_price_row.close * 100
        predicted_up = p.direction == "LONG"
        actual_up = actual_move_pct > 0
        verdict = "CORRECT" if predicted_up == actual_up else "WRONG"

        verdicts.append(PredictionVerdict(
            p.id, p.symbol, created_at.isoformat(), p.direction, p.confidence_pct,
            entry_price_row.close, horizon_price_row.close, round(actual_move_pct, 2), verdict,
        ))

    return verdicts


def summarize_verdicts(verdicts: list[PredictionVerdict]) -> dict:
    scored = [v for v in verdicts if v.verdict in ("CORRECT", "WRONG")]
    correct = sum(1 for v in scored if v.verdict == "CORRECT")
    return {
        "total_predictions": len(verdicts),
        "scored": len(scored),
        "correct": correct,
        "wrong": len(scored) - correct,
        "hit_rate_pct": round(correct / len(scored) * 100, 1) if scored else None,
        "pending": sum(1 for v in verdicts if v.verdict == "PENDING"),
        "no_trade": sum(1 for v in verdicts if v.verdict == "NO_TRADE"),
        "no_data": sum(1 for v in verdicts if v.verdict == "NO_DATA"),
    }
