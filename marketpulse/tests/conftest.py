"""Shared pytest fixtures for tests that need a real Postgres (NewsArticle
and Prediction use JSONB columns, which SQLite cannot compile - confirmed
directly, not assumed - so the lightweight in-memory-SQLite trick used for
HistoricalEvent-only tests doesn't work here). Mirrors the sibling BinMarket
project's own `tests/conftest.py` fixture pattern: `scripts` or CI spins up
a throwaway Postgres and points these env vars at it; running pytest
directly assumes that's already configured.
"""
from __future__ import annotations

import os

os.environ.setdefault("MARKETPULSE_SECRET_KEY", "test-secret-key")
os.environ.setdefault("MARKETPULSE_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("MARKETPULSE_POSTGRES_HOST", "localhost")
os.environ.setdefault("MARKETPULSE_POSTGRES_PORT", "55433")
os.environ.setdefault("MARKETPULSE_POSTGRES_DB", "marketpulse_test")
os.environ.setdefault("MARKETPULSE_POSTGRES_USER", "marketpulse")
os.environ.setdefault("MARKETPULSE_POSTGRES_PASSWORD", "marketpulse")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  (registers tables on Base.metadata)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Each test runs inside its own transaction, rolled back afterwards -
    see BinMarket's own conftest.py for the detailed SAVEPOINT rationale
    (code under test is allowed to call session.commit() without ending
    the outer transaction)."""
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, future=True)
    session = SessionLocal()

    nested = connection.begin_nested()

    from sqlalchemy import event

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        nonlocal nested
        if nested.is_active:
            return
        nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
