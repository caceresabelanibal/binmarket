"""MarketPulse schema - fully independent from BinMarket's.

Everything here is about reading news/social feeds, scoring them, matching
them against a curated table of real historical events, and turning that
into an explainable directional outlook (never a black box - every field a
human reading the dashboard needs is a real column, not something hidden
inside a model's weights).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsArticle(Base):
    """One ingested item from an RSS feed or a public social JSON endpoint
    (see app/feeds.py for the exact source list). `url` is the dedup key -
    the same feed is polled every `ingest_interval_minutes`, so most polls
    see mostly-already-seen items."""

    __tablename__ = "news_articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Computed at ingest time by app/sentiment.py - a lexicon-based score
    # (VADER + a finance-specific word-list boost), not an LLM call. See
    # that module's docstring for exactly how and why.
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)  # -1 (very negative) .. +1 (very positive)
    matched_categories: Mapped[list] = mapped_column(JSONB, default=list)  # e.g. ["monetary_policy"]


class HistoricalEvent(Base):
    """A curated, real, sourced historical event used as a comparison point
    - "the last few times something in this category happened, the market
    moved like X" - never fabricated; see app/events_seed.py for sourcing
    notes on every row."""

    __tablename__ = "historical_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text)
    # Which real symbol market_move_*_pct was computed from (e.g. "^GSPC",
    # or "TSLA" for a single-stock event) - lets app/events_backfill.py
    # re-fetch real prices later to fill in a move that didn't exist yet at
    # seed time (an event less than 5 trading days old). Null only for rows
    # seeded before this column existed, where no further backfill is needed.
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    market_move_1d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_move_5d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_note: Mapped[str] = mapped_column(Text)  # where the % figures came from, and how approximate they are


class MarketPriceDaily(Base):
    """Free daily OHLC cache (Yahoo Finance chart API primary, FRED CSV
    fallback - both keyless, see app/prices.py) used only to score
    predictions against what actually happened. Never used to place trades
    directly - that stays BinMarket's job."""

    __tablename__ = "market_prices_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    price_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    close: Mapped[float] = mapped_column(Float)


class Prediction(Base):
    """One outlook snapshot - the thing the API in api_routes.py exposes for
    another bot to read. `reasoning` always lists the actual contributing
    articles/events so a human (or another system) can audit *why*, never
    just a bare number."""

    __tablename__ = "predictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    horizon_hours: Mapped[int] = mapped_column(Integer, default=48)
    direction: Mapped[str] = mapped_column(String(16))  # LONG | SHORT | NO_TRADE
    confidence_pct: Mapped[float] = mapped_column(Float)
    sentiment_score: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[dict] = mapped_column(JSONB, default=dict)
