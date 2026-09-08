"""Tests for trading-engine's auto-select -> auto-backfill wiring
(trading-engine/app/tick.py). That module lives outside the installed
`binmarket_shared` package, so it's added to sys.path here rather than
imported like the rest of the suite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from binmarket_shared.db.models import Candle, SyncJob

from ._service_import import import_service_module
from .fakes import FakeRedis

_enqueue_backfill_if_needed = import_service_module("trading-engine", "tick")._enqueue_backfill_if_needed


def _add_candles(db, symbol, timeframe, n):
    now = datetime.now(timezone.utc)
    for i in range(n):
        open_time = now - timedelta(hours=n - i)
        db.add(Candle(
            symbol=symbol, timeframe=timeframe, open_time=open_time, close_time=open_time + timedelta(hours=1),
            open=100, high=101, low=99, close=100, volume=10, quote_volume=1000, trades_count=5, is_closed=True,
        ))
    db.flush()


def test_enqueues_a_job_when_there_is_no_history_yet(db):
    redis = FakeRedis()
    _enqueue_backfill_if_needed(db, redis, "NEWUSDT", "5m", days_back=3, min_bars=30)

    assert redis.llen("binmarket:queue:backfill") == 1
    job = db.query(SyncJob).filter(SyncJob.symbol == "NEWUSDT", SyncJob.timeframe == "5m").one()
    assert job.status.value == "PENDING"


def test_does_not_enqueue_when_enough_history_already_exists(db):
    _add_candles(db, "BTCUSDT", "1h", 80)
    redis = FakeRedis()

    _enqueue_backfill_if_needed(db, redis, "BTCUSDT", "1h", days_back=14, min_bars=60)

    assert redis.llen("binmarket:queue:backfill") == 0
    assert db.query(SyncJob).filter(SyncJob.symbol == "BTCUSDT").count() == 0


def test_enqueues_when_existing_history_is_below_the_minimum(db):
    _add_candles(db, "BTCUSDT", "1h", 10)  # below the 60-bar minimum
    redis = FakeRedis()

    _enqueue_backfill_if_needed(db, redis, "BTCUSDT", "1h", days_back=14, min_bars=60)

    assert redis.llen("binmarket:queue:backfill") == 1
