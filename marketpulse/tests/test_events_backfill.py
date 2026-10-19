from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import events_backfill
from app.db import Base
from app.models import HistoricalEvent

# HistoricalEvent has no Postgres-specific column types (unlike NewsArticle/
# Prediction, which use JSONB), so a real, fast, offline SQLite engine is
# enough to test this logic - no live Postgres needed for this file.


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[HistoricalEvent.__table__])
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    yield session
    session.close()


def _midnight_days_ago(days: int) -> datetime:
    # Real HistoricalEvent rows are always constructed as
    # datetime(year, month, day, tzinfo=timezone.utc) - implicit midnight,
    # never a wall-clock time. Matching that here (not datetime.now()'s
    # actual time-of-day) matters: backfill_pending_event_moves finds the
    # event-day index via `close_datetime >= event_date`, which only lines
    # up with the intended day when event_date is itself midnight.
    d = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _event(event_date, symbol="TSLA", move_5d=None):
    return HistoricalEvent(
        event_date=event_date, title="Test event", category="product_launch",
        description="d", symbol=symbol, market_move_1d_pct=-1.0, market_move_5d_pct=move_5d,
        source_note="note",
    )


def test_skips_events_younger_than_the_minimum_window(db, monkeypatch):
    recent = _event(_midnight_days_ago(2))
    db.add(recent)
    db.commit()

    called = []
    monkeypatch.setattr(events_backfill, "fetch_daily_closes", lambda *a, **k: called.append(1) or [])

    updated = events_backfill.backfill_pending_event_moves(db)

    assert updated == 0
    assert called == []  # never even attempted a real fetch - too recent to have a real answer


def test_backfills_a_real_computed_5_day_move_once_old_enough(db, monkeypatch):
    event_date = _midnight_days_ago(10)
    row = _event(event_date)
    db.add(row)
    db.commit()

    # Fake but internally-consistent closes: day before event = 100, event
    # day = 95, then exactly 5 trading days after the event day = 110 ->
    # (110-100)/100*100 = +10%, the number the test asserts on.
    base_date = event_date.date()
    fake_closes = [(base_date - timedelta(days=1), 100.0), (base_date, 95.0)]
    for i in range(1, 6):
        fake_closes.append((base_date + timedelta(days=i), 95.0 + i))
    fake_closes[-1] = (base_date + timedelta(days=5), 110.0)

    monkeypatch.setattr(events_backfill, "fetch_daily_closes", lambda symbol, days_back=25: fake_closes)

    updated = events_backfill.backfill_pending_event_moves(db)

    assert updated == 1
    db.refresh(row)
    assert row.market_move_5d_pct == pytest.approx(10.0)
    assert "Backfilled" in row.source_note


def test_does_not_touch_events_that_already_have_a_5_day_move(db, monkeypatch):
    row = _event(_midnight_days_ago(30), move_5d=3.5)
    db.add(row)
    db.commit()

    called = []
    monkeypatch.setattr(events_backfill, "fetch_daily_closes", lambda *a, **k: called.append(1) or [])

    updated = events_backfill.backfill_pending_event_moves(db)

    assert updated == 0
    assert called == []


def test_leaves_it_pending_if_the_price_source_has_no_data_yet(db, monkeypatch):
    row = _event(_midnight_days_ago(10))
    db.add(row)
    db.commit()

    monkeypatch.setattr(events_backfill, "fetch_daily_closes", lambda *a, **k: [])

    updated = events_backfill.backfill_pending_event_moves(db)

    assert updated == 0
    db.refresh(row)
    assert row.market_move_5d_pct is None  # never guessed - stays pending for the next cycle


def test_events_with_no_symbol_are_never_attempted(db, monkeypatch):
    row = _event(_midnight_days_ago(30), symbol=None)
    db.add(row)
    db.commit()

    called = []
    monkeypatch.setattr(events_backfill, "fetch_daily_closes", lambda *a, **k: called.append(1) or [])

    updated = events_backfill.backfill_pending_event_moves(db)

    assert updated == 0
    assert called == []
