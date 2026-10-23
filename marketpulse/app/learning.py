"""Online learning for the prediction blend's three component weights -
requested directly by the user: "me gustaría que vaya aprendiendo" (of the
times it misses, learn from it and improve future predictions based on
accumulated experience).

Deliberately NOT a trained ML model - that would contradict this entire
project's "never a black box" design (see predictor.py's own docstring).
Instead this is a simple, well-established online-learning technique
(a multiplicative-weights update, sometimes called Hedge / Randomized
Weighted Majority): every so often, look at real predictions that have
already been scored by app/backtest.py (the same honesty check the
dashboard shows), check whether each of the three components - news
sentiment, historical analogues, recent trend - would, ALONE, have called
the real direction correctly, and nudge that component's share of the
blend up if it's been pulling its weight, down if it hasn't. Every
adjustment is written as its own row (models.WeightAdjustment) with the
exact hit-rate numbers that justified it - nothing here is a silently
updated parameter; it's an auditable log, same discipline as every other
number this project produces.

This only ever reweights the three EXISTING, already-explainable
components against each other. It never touches the sentiment lexicon,
the historical event data, or invents a new signal - "learning" here means
"trust whichever of the three signals has actually been right more often
lately a little more," nothing more exotic than that.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .backtest import evaluate_predictions
from .models import Prediction, WeightAdjustment

logger = logging.getLogger("marketpulse.learning")

# The blend's original, hand-chosen weights (predictor.py's own comment:
# "news sentiment is the primary signal... historical analogues and recent
# trend are secondary confirmation") - used until the first real adjustment
# exists, and as the starting point multiplicative updates are applied to.
DEFAULT_WEIGHTS: dict[str, float] = {"news": 0.55, "analogue": 0.25, "trend": 0.20}

# Never let a component's learned weight collapse to near-zero or swallow
# the whole blend - this is meant to rebalance trust between three
# complementary signals over time, not let one noisy early streak silence
# the others permanently.
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.80

# How aggressively one adjustment cycle can move a weight. 0.15 means a
# component sitting at a 100% standalone hit rate gets multiplied by
# exp(0.15 * 0.5) ≈ 1.08 (+8%) that cycle, and one at 0% by exp(-0.075)
# ≈ 0.93 (-7%) - a deliberately gentle nudge, not a snap judgment from one
# batch of real-world results.
LEARNING_RATE = 0.15

# Don't adjust from a tiny, noisy sample - 20 real scored predictions is a
# modest but meaningful floor before trusting a hit-rate number enough to
# act on it.
MIN_SAMPLE_SIZE = 20

# At most once a day - these are real, already-scored predictions
# accumulating over real time, not something that benefits from being
# recomputed every 30-minute ingest cycle.
MIN_HOURS_BETWEEN_UPDATES = 24

_COMPONENT_REASONING_KEYS = {"news": "news_component", "analogue": "analogue_component", "trend": "trend_component"}


def get_current_weights(db: Session) -> dict[str, float]:
    """The weights predictor.py's _blend() should use right now - the most
    recent real adjustment, or the original hand-chosen defaults if the
    model hasn't learned anything yet."""
    latest = db.query(WeightAdjustment).order_by(WeightAdjustment.created_at.desc()).first()
    if latest is None:
        return dict(DEFAULT_WEIGHTS)
    return {"news": latest.news_weight, "analogue": latest.analogue_weight, "trend": latest.trend_weight}


def _component_hit_rates(scored_verdicts, reasoning_by_id: dict[str, dict]) -> dict[str, tuple[float | None, int]]:
    """For each component, among the scored predictions where that
    component actually expressed a directional opinion (a positive or
    negative value - never counted when it was exactly 0, which means "no
    signal," not "predicted flat"), what fraction had its own sign match
    the real outcome's sign? Returns (hit_rate_or_None, sample_count) per
    component."""
    results: dict[str, tuple[float | None, int]] = {}
    for key, reasoning_key in _COMPONENT_REASONING_KEYS.items():
        correct = 0
        applicable = 0
        for v in scored_verdicts:
            reasoning = reasoning_by_id.get(v.prediction_id) or {}
            component = reasoning.get(reasoning_key)
            if not component:
                continue
            applicable += 1
            component_called_up = component > 0
            actual_up = (v.actual_move_pct or 0) > 0
            if component_called_up == actual_up:
                correct += 1
        results[key] = (correct / applicable if applicable else None, applicable)
    return results


def _apply_multiplicative_update(
    current_weights: dict[str, float], hit_rates: dict[str, float | None],
) -> dict[str, float]:
    """The actual learning rule, kept pure (no DB) so it's directly
    unit-testable: a component whose standalone hit rate was above 50%
    gets its weight scaled up; below 50%, scaled down; exactly 50% (or no
    data this cycle) is left untouched. Renormalized so the three weights
    always sum to 1.0, both before and after clamping to [MIN_WEIGHT,
    MAX_WEIGHT] (clamping alone can break that sum)."""
    updated = {}
    for key, weight in current_weights.items():
        hit_rate = hit_rates.get(key)
        if hit_rate is None:
            updated[key] = weight
            continue
        updated[key] = weight * math.exp(LEARNING_RATE * (hit_rate - 0.5))

    total = sum(updated.values())
    clamped = {key: max(MIN_WEIGHT, min(MAX_WEIGHT, value / total)) for key, value in updated.items()}
    total_after_clamp = sum(clamped.values())
    return {key: value / total_after_clamp for key, value in clamped.items()}


def update_weights_if_due(db: Session, now: datetime | None = None) -> WeightAdjustment | None:
    """Runs every scheduler cycle (cheap - gates internally) but only
    actually adjusts weights at most once every MIN_HOURS_BETWEEN_UPDATES,
    and only once there's a real enough sample to trust. Returns the new
    WeightAdjustment row if one was made, else None (nothing to report -
    either too soon, or not enough real scored predictions yet)."""
    now = now or datetime.now(timezone.utc)

    last = db.query(WeightAdjustment).order_by(WeightAdjustment.created_at.desc()).first()
    if last is not None:
        last_at = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
        if now - last_at < timedelta(hours=MIN_HOURS_BETWEEN_UPDATES):
            return None

    verdicts = evaluate_predictions(db, days_back=60)
    scored = [v for v in verdicts if v.verdict in ("CORRECT", "WRONG")]
    if len(scored) < MIN_SAMPLE_SIZE:
        return None

    reasoning_by_id = {
        row.id: row.reasoning
        for row in db.query(Prediction).filter(Prediction.id.in_([v.prediction_id for v in scored])).all()
    }

    hit_rate_and_count = _component_hit_rates(scored, reasoning_by_id)
    hit_rates = {key: value[0] for key, value in hit_rate_and_count.items()}

    current_weights = get_current_weights(db)
    new_weights = _apply_multiplicative_update(current_weights, hit_rates)

    note_parts = [
        f"{key}: {current_weights[key]:.3f} -> {new_weights[key]:.3f} "
        f"(hit rate {hit_rates[key]:.1%} over {hit_rate_and_count[key][1]} calls)"
        if hit_rates[key] is not None
        else f"{key}: {current_weights[key]:.3f} -> {new_weights[key]:.3f} (no directional opinion this cycle)"
        for key in current_weights
    ]
    note = f"Based on {len(scored)} real scored predictions (last {60} days). " + "; ".join(note_parts)

    row = WeightAdjustment(
        news_weight=new_weights["news"], analogue_weight=new_weights["analogue"], trend_weight=new_weights["trend"],
        news_hit_rate=hit_rates["news"], analogue_hit_rate=hit_rates["analogue"], trend_hit_rate=hit_rates["trend"],
        sample_size=len(scored), note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Adjusted model weights: %s", note)
    return row
