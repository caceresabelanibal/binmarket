from __future__ import annotations

import pandas as pd
import pytest

from binmarket_shared.quant.seasonality import hourly_edge


def _hourly_df(days=7, base=100.0):
    idx = pd.date_range("2024-01-01", periods=days * 24, freq="h", tz="UTC")
    rows = []
    price = base
    for ts in idx:
        # Hour 10 UTC always goes up 1%, hour 3 UTC always goes down 1%,
        # every other hour is flat - gives each hour a deterministic,
        # easily-asserted average return.
        if ts.hour == 10:
            close = price * 1.01
        elif ts.hour == 3:
            close = price * 0.99
        else:
            close = price
        rows.append({"open": price, "high": max(price, close), "low": min(price, close), "close": close, "volume": 1000.0})
        price = close
    return pd.DataFrame(rows, index=idx)


def test_empty_df_returns_zero_edge_with_no_samples():
    edge = hourly_edge(pd.DataFrame(), hour_utc=10)
    assert edge.avg_return_pct == 0.0
    assert edge.sample_count == 0


def test_missing_ohlc_columns_returns_zero_edge():
    df = pd.DataFrame({"volume": [1, 2, 3]}, index=pd.date_range("2024-01-01", periods=3, freq="h"))
    edge = hourly_edge(df, hour_utc=5)
    assert edge.sample_count == 0


def test_hour_with_a_consistent_positive_return_is_detected():
    df = _hourly_df(days=7)
    edge = hourly_edge(df, hour_utc=10, lookback_days=7)
    assert edge.avg_return_pct == pytest.approx(1.0, abs=1e-6)
    assert edge.sample_count == 7


def test_hour_with_a_consistent_negative_return_is_detected():
    df = _hourly_df(days=7)
    edge = hourly_edge(df, hour_utc=3, lookback_days=7)
    assert edge.avg_return_pct == pytest.approx(-1.0, abs=1e-6)
    assert edge.sample_count == 7


def test_flat_hour_has_zero_edge():
    df = _hourly_df(days=7)
    edge = hourly_edge(df, hour_utc=12, lookback_days=7)
    assert edge.avg_return_pct == pytest.approx(0.0, abs=1e-6)
    assert edge.sample_count == 7


def test_lookback_window_limits_how_far_back_samples_are_counted():
    df = _hourly_df(days=14)
    edge_short = hourly_edge(df, hour_utc=10, lookback_days=7)
    edge_long = hourly_edge(df, hour_utc=10, lookback_days=14)
    assert edge_short.sample_count == 7
    assert edge_long.sample_count == 14


def test_hour_never_seen_in_the_window_has_zero_samples():
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    df = pd.DataFrame({"open": [1] * 5, "high": [1] * 5, "low": [1] * 5, "close": [1] * 5, "volume": [1] * 5}, index=idx)
    edge = hourly_edge(df, hour_utc=22, lookback_days=7)
    assert edge.sample_count == 0
    assert edge.avg_return_pct == 0.0
