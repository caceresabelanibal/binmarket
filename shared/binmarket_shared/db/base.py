"""SQLAlchemy engine/session setup shared by all Python services.

We deliberately use a synchronous SQLAlchemy engine (psycopg2) rather than an
async driver: this is a single-user internal tool with modest throughput, and
a sync engine keeps the whole codebase (backend, trading-engine, market-data,
Alembic) on one simple, well-understood execution model. Asyncio services
(trading-engine, market-data) wrap DB calls in `asyncio.to_thread` so they
never block the event loop that runs the Binance WebSocket connections.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from binmarket_shared.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_session() -> Generator[Session, None, None]:
    """FastAPI-style dependency: yields a session, closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for non-FastAPI code (trading-engine, market-data, scripts).

    Commits on success, rolls back on error, always closes.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
