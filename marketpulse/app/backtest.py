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
    created_at: str
    direction: str
    confidence_pct: float
    price_at_prediction: float | None
    price_at_horizon: float | None
    actual_move_pct: float | None
    verdict: str  # "CORRECT" | "WRONG" | "PENDING" | "NO_TRADE" | "NO_DATA"


def _closest_price(prices: list[MarketPriceDaily], target: datetime) -> MarketPriceDaily | None:
    """Nearest cached daily close to `target` within 2 days either way -
    daily data can't line up to the exact hour a prediction was made."""
    candidates = [p for p in prices if abs((p.price_date - target).total_seconds()) <= 2 * 86400]
    if not candidates:
        return None
    return min(candidates, key=lambda p: abs((p.price_date - target).total_seconds()))


def evaluate_predictions(db: Session, symbol: str, limit: int = 60) -> list[PredictionVerdict]:
    predictions = (
        db.query(Prediction)
        .filter(Prediction.symbol == symbol)
        .order_by(Prediction.created_at.desc())
        .limit(limit)
        .all()
    )
    prices = db.query(MarketPriceDaily).filter(MarketPriceDaily.symbol == symbol).all()

    now = datetime.now(timezone.utc)
    verdicts: list[PredictionVerdict] = []
    for p in predictions:
        created_at = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=timezone.utc)
        horizon_time = created_at + timedelta(hours=p.horizon_hours)

        entry_price_row = _closest_price(prices, created_at)
        entry_price = entry_price_row.close if entry_price_row else None

        if p.direction == "NO_TRADE":
            verdicts.append(PredictionVerdict(
                p.id, created_at.isoformat(), p.direction, p.confidence_pct,
                entry_price, None, None, "NO_TRADE",
            ))
            continue

        if now < horizon_time:
            verdicts.append(PredictionVerdict(
                p.id, created_at.isoformat(), p.direction, p.confidence_pct,
                entry_price, None, None, "PENDING",
            ))
            continue

        horizon_price_row = _closest_price(prices, horizon_time)
        if not entry_price_row or not horizon_price_row:
            verdicts.append(PredictionVerdict(
                p.id, created_at.isoformat(), p.direction, p.confidence_pct,
                entry_price, horizon_price_row.close if horizon_price_row else None, None, "NO_DATA",
            ))
            continue

        actual_move_pct = (horizon_price_row.close - entry_price_row.close) / entry_price_row.close * 100
        predicted_up = p.direction == "LONG"
        actual_up = actual_move_pct > 0
        verdict = "CORRECT" if predicted_up == actual_up else "WRONG"

        verdicts.append(PredictionVerdict(
            p.id, created_at.isoformat(), p.direction, p.confidence_pct,
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
