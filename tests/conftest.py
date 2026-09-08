"""Shared pytest fixtures.

DB-touching tests need a real Postgres (models use `postgresql.JSONB`, so
SQLite can't stand in). `scripts/run-tests.*` spins up a throwaway Postgres
+ Redis pair, points these env vars at them, and tears them down afterwards
— the same thing CI should do. Running pytest directly assumes that
environment is already configured (POSTGRES_HOST/PORT/DB/USER/PASSWORD).
"""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "55432")
os.environ.setdefault("POSTGRES_DB", "binmarket_test")
os.environ.setdefault("POSTGRES_USER", "binmarket")
os.environ.setdefault("POSTGRES_PASSWORD", "binmarket")
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/0")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from binmarket_shared.config import settings
from binmarket_shared.db.base import Base
from binmarket_shared.db import models  # noqa: F401  (registers tables on Base.metadata)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Each test runs inside its own transaction, rolled back afterwards —
    tests never see each other's data and never need manual cleanup.

    Code under test is allowed to call `session.commit()` (some real code
    paths do, correctly — e.g. a job that must be visible to another process
    before it's queued). A plain `connection.begin()` would let that commit
    end the *outer* transaction too, breaking isolation for the rest of the
    test. The standard SQLAlchemy fix: run the outer transaction as a
    SAVEPOINT and restart a fresh one every time the session's transaction
    ends, so `session.commit()` only ever closes the savepoint, never the
    connection's real transaction — see SQLAlchemy's "joining a session into
    an external transaction" recipe.
    """
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, future=True)
    session = SessionLocal()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def app_settings(db):
    from binmarket_shared.db.models import AppSettings

    row = AppSettings(id=1)
    db.add(row)
    db.flush()
    return row
