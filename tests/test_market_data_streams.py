"""Tests for market-data's stream selection and bandwidth categorization
(market-data/app/ingest.py).
"""
from __future__ import annotations

import asyncio

from binmarket_shared.redis_keys import bandwidth_bucket_key, orderbook_top_key

from ._service_import import import_service_module
from .fakes import AsyncFakeRedis

_ingest = import_service_module("market-data", "ingest")
_build_streams = _ingest._build_streams
_handle_message = _ingest._handle_message
ESSENTIAL_TIMEFRAMES = _ingest.ESSENTIAL_TIMEFRAMES

# Binance's real partial book depth payload: no "e"/"s" field at all, and
# the price levels are "bids"/"asks", not the short "b"/"a" keys used by the
# diff-depth stream. The symbol is only identifiable via the combined-stream
# name ("btcusdt@depth5"), never inside the payload body.
REAL_DEPTH_PAYLOAD = {
    "lastUpdateId": 12345,
    "bids": [["27000.10", "1.5"], ["27000.00", "2.0"]],
    "asks": [["27000.20", "0.8"], ["27000.30", "1.1"]],
}


def test_essential_mode_only_streams_regime_and_scalping_timeframes():
    streams = _build_streams(["BTCUSDT"], all_timeframes=False, depth_speed_ms=1000)
    kline_streams = [s for s in streams if "@kline_" in s]

    assert set(ESSENTIAL_TIMEFRAMES) == {"1h", "5m"}
    assert len(kline_streams) == 2
    assert "btcusdt@kline_1h" in kline_streams
    assert "btcusdt@kline_5m" in kline_streams
    assert "btcusdt@kline_1m" not in kline_streams  # the actual bandwidth cut


def test_all_timeframes_mode_streams_all_eight():
    streams = _build_streams(["BTCUSDT"], all_timeframes=True, depth_speed_ms=1000)
    kline_streams = [s for s in streams if "@kline_" in s]
    assert len(kline_streams) == 8


def test_depth_speed_controls_the_stream_suffix():
    fast = _build_streams(["BTCUSDT"], all_timeframes=False, depth_speed_ms=100)
    slow = _build_streams(["BTCUSDT"], all_timeframes=False, depth_speed_ms=1000)

    assert "btcusdt@depth5@100ms" in fast
    assert "btcusdt@depth5" in slow
    assert "btcusdt@depth5@100ms" not in slow


def test_streams_are_built_per_symbol():
    streams = _build_streams(["BTCUSDT", "ETHUSDT"], all_timeframes=False, depth_speed_ms=1000)
    assert any(s.startswith("btcusdt@") for s in streams)
    assert any(s.startswith("ethusdt@") for s in streams)
    # ticker + depth + 2 essential klines = 4 streams per symbol
    assert len(streams) == 8


def test_real_depth_payload_is_attributed_to_symbol_from_stream_name():
    redis = AsyncFakeRedis()
    asyncio.run(_handle_message(redis, REAL_DEPTH_PAYLOAD, 200, "btcusdt@depth5"))

    stored = redis.store[orderbook_top_key("BTCUSDT")]
    assert '"bid": 27000.1' in stored
    assert '"ask": 27000.2' in stored


def test_real_depth_payload_without_stream_name_is_dropped_not_misattributed():
    redis = AsyncFakeRedis()
    asyncio.run(_handle_message(redis, REAL_DEPTH_PAYLOAD, 200, None))

    assert redis.store == {}


def test_real_depth_payload_counts_toward_orderbook_bandwidth():
    redis = AsyncFakeRedis()
    asyncio.run(_handle_message(redis, REAL_DEPTH_PAYLOAD, 200, "ethusdt@depth5"))

    from datetime import datetime, timezone

    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    assert redis.counters[bandwidth_bucket_key("orderbook", bucket)] == 200
