from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import events_seed
from app.db import Base
from app.models import HistoricalEvent

# HistoricalEvent has no Postgres-specific column types, so a real, fast,
# offline SQLite engine is enough - no live Postgres needed for this file.


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[HistoricalEvent.__table__])
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    yield session
    session.close()


def test_seeds_every_row_into_an_empty_table(db):
    inserted = events_seed.seed_historical_events(db)

    assert inserted == len(events_seed.SEED_EVENTS)
    assert db.query(HistoricalEvent).count() == len(events_seed.SEED_EVENTS)


def test_running_it_again_inserts_nothing_new(db):
    events_seed.seed_historical_events(db)

    inserted_again = events_seed.seed_historical_events(db)

    assert inserted_again == 0
    assert db.query(HistoricalEvent).count() == len(events_seed.SEED_EVENTS)


def test_a_newly_added_seed_event_is_picked_up_on_an_already_populated_table(db, monkeypatch):
    """Real production scenario this covers: the table was already seeded
    with an older, shorter SEED_EVENTS list (e.g. 9 rows) before this file
    grew to include more real events. Deploying the new code must add the
    new rows without wiping or duplicating what's already there."""
    original = list(events_seed.SEED_EVENTS)
    monkeypatch.setattr(events_seed, "SEED_EVENTS", original[:-1])
    events_seed.seed_historical_events(db)
    assert db.query(HistoricalEvent).count() == len(original) - 1

    monkeypatch.setattr(events_seed, "SEED_EVENTS", original)
    inserted = events_seed.seed_historical_events(db)

    assert inserted == 1
    assert db.query(HistoricalEvent).count() == len(original)
    assert db.query(HistoricalEvent).filter(HistoricalEvent.title == original[-1]["title"]).count() == 1


def test_every_category_used_in_sentiment_tagging_has_at_least_one_real_analogue(db):
    """The predictor can only surface an analogue for a category that
    actually has one - this would have silently caught the real gap found
    in production, where 'trade_policy' had zero HistoricalEvent rows even
    though it was a live sentiment category."""
    from app.sentiment import EVENT_CATEGORIES

    seeded_categories = {row["category"] for row in events_seed.SEED_EVENTS}

    assert set(EVENT_CATEGORIES) <= seeded_categories
