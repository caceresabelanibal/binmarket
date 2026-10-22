"""Regression tests for the real production bug: predictions are generated
every `ingest_interval_minutes` (30 by default) with a 48h horizon, but
evaluate_predictions used to take the 60 MOST RECENT rows (a row count, not
a time window) - 60 * 30min only reaches back ~30 real hours, always LESS
than the 48h horizon needed before a verdict can exist. The backtest could
never show a single CORRECT/WRONG, no matter how long the service ran.
Confirmed live: 60/60 recent predictions were PENDING or NO_TRADE, 0 scored,
even though the oldest stored prediction was already ~65 hours old.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.backtest import evaluate_predictions
from app.models import MarketPriceDaily, Prediction


def _price(symbol, price_date, close):
    return MarketPriceDaily(symbol=symbol, price_date=price_date, close=close)


def _prediction(symbol, created_at, direction, horizon_hours=48):
    return Prediction(
        symbol=symbol, created_at=created_at, horizon_hours=horizon_hours,
        direction=direction, confidence_pct=50.0, sentiment_score=0.1, reasoning={},
    )


def test_a_prediction_whose_horizon_has_passed_gets_a_real_verdict(db):
    symbol = "^IXIC"
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(hours=60)  # horizon (48h) has elapsed

    db.add(_prediction(symbol, created_at, "LONG"))
    db.add(_price(symbol, created_at, 100.0))
    db.add(_price(symbol, created_at + timedelta(hours=48), 105.0))  # went up - LONG was correct
    db.commit()

    verdicts = evaluate_predictions(db, symbol, days_back=14)

    assert len(verdicts) == 1
    assert verdicts[0].verdict == "CORRECT"


def test_wrong_direction_is_scored_wrong(db):
    symbol = "^IXIC"
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(hours=60)

    db.add(_prediction(symbol, created_at, "LONG"))
    db.add(_price(symbol, created_at, 100.0))
    db.add(_price(symbol, created_at + timedelta(hours=48), 95.0))  # went down - LONG was wrong
    db.commit()

    verdicts = evaluate_predictions(db, symbol, days_back=14)

    assert verdicts[0].verdict == "WRONG"


def test_a_scoreable_old_prediction_is_not_crowded_out_by_many_recent_ones(db):
    """Simulates the exact failure mode: 100 very recent (still-pending)
    predictions plus 1 old enough to be scored - the old .limit(60) would
    never even fetch the scoreable one, since it isn't among the 60 most
    recent rows."""
    symbol = "^IXIC"
    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=60)

    db.add(_prediction(symbol, old_enough, "LONG"))
    db.add(_price(symbol, old_enough, 100.0))
    db.add(_price(symbol, old_enough + timedelta(hours=48), 110.0))
    for i in range(100):
        db.add(_prediction(symbol, now - timedelta(minutes=30 * i), "NO_TRADE"))
    db.commit()

    verdicts = evaluate_predictions(db, symbol, days_back=14)

    scored = [v for v in verdicts if v.verdict in ("CORRECT", "WRONG")]
    assert len(scored) == 1
    assert scored[0].verdict == "CORRECT"


def test_predictions_outside_the_window_are_excluded(db):
    symbol = "^IXIC"
    now = datetime.now(timezone.utc)
    too_old = now - timedelta(days=30)

    db.add(_prediction(symbol, too_old, "LONG"))
    db.commit()

    verdicts = evaluate_predictions(db, symbol, days_back=14)

    assert verdicts == []
