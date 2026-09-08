"""Regression tests for market-data's gap-aware backfill range computation
(market-data/app/backfill.py). That module lives outside the installed
`binmarket_shared` package, so it's added to sys.path here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from binmarket_shared.db.models import Candle

from ._service_import import import_service_module

_backfill = import_service_module("market-data", "backfill")
_ms = _backfill._ms
_ranges_to_fetch = _backfill._ranges_to_fetch


def _add_candle(db, symbol, timeframe, open_time):
    db.add(Candle(
        symbol=symbol, timeframe=timeframe, open_time=open_time, close_time=open_time + timedelta(hours=1),
        open=1, high=1, low=1, close=1, volume=1, quote_volume=1, trades_count=1, is_closed=True,
    ))
    db.flush()


def test_fresh_symbol_with_no_candles_fetches_the_full_requested_range(db):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)

    ranges = _ranges_to_fetch(db, "NEWUSDT", "1h", start, _ms(now))

    assert ranges == [(_ms(start), _ms(now))]


def test_a_lone_live_streamed_candle_does_not_block_the_historical_backfill(db):
    """This is the exact bug found live: auto-selecting a symbol starts
    streaming candles immediately, so by the time the backfill job runs
    there's already one recent candle. The old "resume from latest" logic
    saw that and concluded there was nothing left to fetch — the real,
    requested history before it must still be fetched.
    """
    now = datetime.now(timezone.utc)
    live_candle_time = now - timedelta(minutes=5)
    _add_candle(db, "BMTUSDT", "5m", live_candle_time)

    requested_start = now - timedelta(days=3)
    ranges = _ranges_to_fetch(db, "BMTUSDT", "5m", requested_start, _ms(now))

    # The backward (historical) range is the one that matters for this bug:
    # the old logic never produced it at all once any live candle existed.
    # A forward range for the few minutes since that live candle is also
    # legitimate and expected — it isn't what's being guarded against here.
    backward = [r for r in ranges if r[0] == _ms(requested_start)]
    assert len(backward) == 1
    assert backward[0][1] == _ms(live_candle_time)  # stops right before the one candle we already have


def test_does_not_refetch_a_range_that_is_already_fully_covered(db):
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=5)
    end = start + timedelta(hours=4)  # fully covered: start, start+1h, ..., end
    cursor = start
    while cursor <= end:
        _add_candle(db, "BTCUSDT", "1h", cursor)
        cursor += timedelta(hours=1)

    ranges = _ranges_to_fetch(db, "BTCUSDT", "1h", start, _ms(end))

    assert ranges == []


def test_fills_only_the_forward_gap_when_history_already_starts_early_enough(db):
    now = datetime.now(timezone.utc)
    old_candle_time = now - timedelta(days=10)
    _add_candle(db, "BTCUSDT", "1h", old_candle_time)

    requested_start = now - timedelta(days=5)  # later than what we already have
    ranges = _ranges_to_fetch(db, "BTCUSDT", "1h", requested_start, _ms(now))

    assert len(ranges) == 1
    range_start, range_end = ranges[0]
    assert range_start == _ms(old_candle_time) + 1
    assert range_end == _ms(now)


def test_fills_both_a_backward_and_forward_gap_when_both_exist(db):
    now = datetime.now(timezone.utc)
    middle_candle_time = now - timedelta(days=5)
    _add_candle(db, "BTCUSDT", "1h", middle_candle_time)

    requested_start = now - timedelta(days=10)
    ranges = _ranges_to_fetch(db, "BTCUSDT", "1h", requested_start, _ms(now))

    assert len(ranges) == 2
    assert ranges[0] == (_ms(requested_start), _ms(middle_candle_time))
    assert ranges[1] == (_ms(middle_candle_time) + 1, _ms(now))
