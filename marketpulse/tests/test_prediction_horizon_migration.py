"""Regression tests for the real rule change: the prediction horizon moved
from 48h to 24h (user feedback: "si sucede algo hoy, tengo que saber como
operar mañana" - 48h meant a same-day event couldn't be scored, or acted
on, until the day after tomorrow). Already-stored predictions must be
migrated to the new horizon too, not left stuck evaluating against
whatever was in effect when they were created.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.predictor import PREDICTION_HORIZON_HOURS
from app.models import Prediction
from app.seed import migrate_prediction_horizon


def _prediction(horizon_hours):
    return Prediction(
        symbol="^IXIC", created_at=datetime.now(timezone.utc), horizon_hours=horizon_hours,
        direction="LONG", confidence_pct=50.0, sentiment_score=0.1, reasoning={},
    )


def test_an_old_48h_prediction_is_migrated_to_the_current_horizon(db):
    assert PREDICTION_HORIZON_HOURS == 24
    row = _prediction(48)
    db.add(row)
    db.commit()

    migrated = migrate_prediction_horizon(db)

    assert migrated == 1
    db.refresh(row)
    assert row.horizon_hours == 24


def test_a_prediction_already_on_the_current_horizon_is_left_untouched(db):
    row = _prediction(PREDICTION_HORIZON_HOURS)
    db.add(row)
    db.commit()

    migrated = migrate_prediction_horizon(db)

    assert migrated == 0


def test_running_it_twice_is_a_no_op_the_second_time(db):
    db.add(_prediction(48))
    db.commit()

    first = migrate_prediction_horizon(db)
    second = migrate_prediction_horizon(db)

    assert first == 1
    assert second == 0
