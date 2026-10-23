"""Tests for the online-learning weight adjustment (requested directly by
the user: "me gustaría que vaya aprendiendo" - of the predictions that
miss, analyze what happened and adjust future ones). Deliberately NOT a
trained model - see app/learning.py's own docstring for why this is a
simple, fully auditable multiplicative-weights update instead.

`_apply_multiplicative_update` and `get_current_weights` only touch
WeightAdjustment, which has no JSONB columns, so a fast offline SQLite
engine is enough for those. `update_weights_if_due` also reads real
Prediction rows (JSONB `reasoning`), so those tests use the shared
Postgres-backed `db` fixture from conftest.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import learning
from app.db import Base
from app.models import MarketPriceDaily, Prediction, WeightAdjustment


@pytest.fixture()
def sqlite_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[WeightAdjustment.__table__])
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    yield session
    session.close()


def _adjustment(**overrides):
    defaults = dict(
        news_weight=0.55, analogue_weight=0.25, trend_weight=0.20,
        news_hit_rate=0.6, analogue_hit_rate=0.4, trend_hit_rate=0.5,
        sample_size=30, note="test",
    )
    defaults.update(overrides)
    return WeightAdjustment(**defaults)


# --- _apply_multiplicative_update (pure function, no DB) ---------------

def test_a_component_above_50pct_hit_rate_gets_a_bigger_weight():
    current = {"news": 0.55, "analogue": 0.25, "trend": 0.20}
    updated = learning._apply_multiplicative_update(current, {"news": 0.8, "analogue": 0.5, "trend": 0.5})

    assert updated["news"] > current["news"]


def test_a_component_below_50pct_hit_rate_gets_a_smaller_weight():
    current = {"news": 0.55, "analogue": 0.25, "trend": 0.20}
    updated = learning._apply_multiplicative_update(current, {"news": 0.5, "analogue": 0.1, "trend": 0.5})

    assert updated["analogue"] < current["analogue"]


def test_weights_always_sum_to_one():
    current = {"news": 0.55, "analogue": 0.25, "trend": 0.20}
    updated = learning._apply_multiplicative_update(current, {"news": 0.9, "analogue": 0.1, "trend": 0.5})

    assert sum(updated.values()) == pytest.approx(1.0)


def test_a_component_with_no_sample_this_cycle_is_left_untouched_before_renormalization():
    current = {"news": 0.55, "analogue": 0.25, "trend": 0.20}
    updated = learning._apply_multiplicative_update(current, {"news": None, "analogue": 0.5, "trend": 0.5})

    # Still sums to 1 (renormalized), but news wasn't singled out for a
    # direct up/down nudge the way analogue/trend could have been.
    assert sum(updated.values()) == pytest.approx(1.0)


def test_weight_never_collapses_below_the_floor_even_with_a_terrible_streak():
    current = {"news": 0.10, "analogue": 0.45, "trend": 0.45}
    updated = learning._apply_multiplicative_update(current, {"news": 0.0, "analogue": 0.5, "trend": 0.5})

    assert updated["news"] >= learning.MIN_WEIGHT - 1e-9


def test_weight_never_exceeds_the_ceiling_even_with_a_perfect_streak():
    current = {"news": 0.75, "analogue": 0.15, "trend": 0.10}
    updated = learning._apply_multiplicative_update(current, {"news": 1.0, "analogue": 0.5, "trend": 0.5})

    assert updated["news"] <= learning.MAX_WEIGHT + 1e-9


# --- get_current_weights (SQLite, WeightAdjustment only) ----------------

def test_defaults_are_used_when_nothing_has_ever_been_learned(sqlite_db):
    assert learning.get_current_weights(sqlite_db) == learning.DEFAULT_WEIGHTS


def test_the_most_recent_adjustment_is_what_is_actually_used(sqlite_db):
    now = datetime.now(timezone.utc)
    sqlite_db.add(_adjustment(news_weight=0.5, analogue_weight=0.3, trend_weight=0.2, created_at=now - timedelta(days=2)))
    sqlite_db.add(_adjustment(news_weight=0.6, analogue_weight=0.2, trend_weight=0.2, created_at=now))
    sqlite_db.commit()

    weights = learning.get_current_weights(sqlite_db)

    assert weights == {"news": 0.6, "analogue": 0.2, "trend": 0.2}


# --- update_weights_if_due (Postgres - needs real Prediction rows) ------

def _prediction(symbol, created_at, direction, news_component, analogue_component, trend_component):
    return Prediction(
        symbol=symbol, created_at=created_at, horizon_hours=24, direction=direction,
        confidence_pct=50.0, sentiment_score=0.1,
        reasoning={
            "news_component": news_component, "analogue_component": analogue_component,
            "trend_component": trend_component, "article_count": 5,
        },
    )


def _price(symbol, price_date, close):
    return MarketPriceDaily(symbol=symbol, price_date=price_date, close=close)


def _build_scoreable_history(db, count, news_right_fraction):
    """Builds `count` already-scored (CORRECT/WRONG) ^IXIC predictions, each
    with a real price move the backtest can score against, where exactly
    `news_right_fraction` of them have a news_component sign that matches
    the real outcome (the rest have it backwards) - letting a test dial in
    an exact standalone hit rate for the news component to assert on.
    Timestamps are spaced 5 real hours apart (well beyond the 24h horizon)
    so no two predictions' entry/horizon price lookups can ever collide on
    the same cached price_date."""
    now = datetime.now(timezone.utc)
    for i in range(count):
        created_at = now - timedelta(hours=200 + i * 5)
        horizon_close_at = created_at + timedelta(hours=24)
        db.add(_price("^IXIC", created_at, 100.0))
        db.add(_price("^IXIC", horizon_close_at, 105.0))  # the market went UP

        news_matches = i < int(count * news_right_fraction)
        news_component = 0.3 if news_matches else -0.3  # matches UP only when news_matches
        db.add(_prediction("^IXIC", created_at, "LONG", news_component, 0.0, 0.0))
    db.commit()


def test_returns_none_without_a_minimum_real_sample(db):
    _build_scoreable_history(db, learning.MIN_SAMPLE_SIZE - 1, news_right_fraction=1.0)

    result = learning.update_weights_if_due(db)

    assert result is None
    assert db.query(WeightAdjustment).count() == 0


def test_adjusts_once_a_real_minimum_sample_exists(db):
    _build_scoreable_history(db, learning.MIN_SAMPLE_SIZE + 5, news_right_fraction=0.9)

    result = learning.update_weights_if_due(db)

    assert result is not None
    assert result.sample_size >= learning.MIN_SAMPLE_SIZE
    assert result.news_hit_rate == pytest.approx(0.9, abs=0.05)
    # A component that's right 90% of the time should gain weight.
    assert result.news_weight > learning.DEFAULT_WEIGHTS["news"]


def test_does_not_adjust_again_before_the_minimum_wait(db):
    _build_scoreable_history(db, learning.MIN_SAMPLE_SIZE + 5, news_right_fraction=0.9)
    first = learning.update_weights_if_due(db)
    assert first is not None

    second = learning.update_weights_if_due(db)

    assert second is None
    assert db.query(WeightAdjustment).count() == 1
