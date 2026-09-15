from __future__ import annotations

import pandas as pd
import pytest

from binmarket_shared.quant.regime import RegimeReading, TrendRegime, VolatilityRegime
from binmarket_shared.trading.strategies.base import OpenPositionView, StrategyContext
from binmarket_shared.trading.strategies.day_trading import DayTradingStrategy
from binmarket_shared.trading.strategies.registry import STRATEGY_REGISTRY, get_strategy

# Any real "now" could land on/after the default eod_flatten_hour_utc=23,
# which would make every non-EOD-focused test flaky depending on when it
# happens to run. Tests that aren't specifically about the EOD gate pin it
# out of reach (24 - now_hour is always 0-23, so >= 24 never fires); the
# EOD-specific tests pin it to 0, which always fires.
NEVER_EOD = {"eod_flatten_hour_utc": 24}


def _uptrend_1h_df(n=80, start_price=100.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    closes = [start_price * (1 + 0.003 * i) for i in range(n)]
    return pd.DataFrame(
        {
            "open": [c * 0.999 for c in closes], "high": [c * 1.002 for c in closes],
            "low": [c * 0.997 for c in closes], "close": closes,
            "volume": [1000.0 + i * 5 for i in range(n)],
        },
        index=idx,
    )


def _ctx(df, regime, current_price, open_position=None):
    return StrategyContext(
        df=df, symbol="TESTUSDT", timeframe="1h", regime=regime, current_price=current_price,
        best_bid=current_price, best_ask=current_price, available_capital=1000.0,
        current_total_exposure_value=0.0, max_total_exposure_pct=50.0, max_position_size_pct=20.0,
        risk_per_trade_pct=1.0, taker_fee_pct=0.1, default_slippage_pct=0.05,
        min_expected_net_profit_pct=0.05, open_position=open_position,
    )


def test_day_trading_is_registered_and_tried_first():
    assert "day_trading" in STRATEGY_REGISTRY
    assert get_strategy("day_trading") is not None
    assert next(iter(STRATEGY_REGISTRY)) == "day_trading"


def test_preferred_timeframe_is_1h_same_series_as_regime_classification():
    assert DayTradingStrategy.preferred_timeframe == "1h"


@pytest.mark.parametrize(
    "volatility,expected",
    [
        (VolatilityRegime.LOW, True),
        (VolatilityRegime.NORMAL, True),
        (VolatilityRegime.HIGH, True),
        (VolatilityRegime.EXTREME, False),
    ],
)
def test_eligibility_excludes_only_extreme_volatility(volatility, expected):
    strategy = DayTradingStrategy()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=volatility, adx_value=25, volatility_pct=1.0)
    assert strategy.is_regime_eligible(regime) is expected


def test_never_buys_again_while_a_position_is_already_open():
    strategy = DayTradingStrategy(params=NEVER_EOD)
    df = _uptrend_1h_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(
        df, regime, float(df["close"].iloc[-1]),
        open_position=OpenPositionView(entry_price=99, quantity=1, stop_loss=95, take_profit=101, trailing_stop_pct=None, highest_price_since_entry=100, opened_at=None),
    )
    signal = strategy.generate_signal(ctx)
    assert signal.action == "HOLD"


def test_buys_on_a_strong_uptrend_when_seasonality_cannot_block_it():
    # RSI on a smooth, uninterrupted synthetic uptrend runs deep into
    # overbought territory - opening the RSI band here isolates what this
    # test is actually about (seasonality not vetoing the entry) from the
    # unrelated, realistic RSI entry-range gate exercised elsewhere.
    strategy = DayTradingStrategy(params={
        **NEVER_EOD, "min_opportunity_score": 0, "min_seasonality_edge_pct": -1000.0,
        "min_entry_rsi": 0.0, "max_entry_rsi": 100.0,
    })
    df = _uptrend_1h_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(df, regime, float(df["close"].iloc[-1]))

    signal = strategy.generate_signal(ctx)

    assert signal.action == "BUY"
    assert signal.stop_loss < signal.entry_price < signal.take_profit


def test_negative_hourly_seasonality_blocks_a_buy_outright():
    """An impossible-to-clear seasonality floor must veto the entry even
    when every technical condition is otherwise favorable - this is what
    makes seasonality a real gate, not a cosmetic score nudge."""
    strategy = DayTradingStrategy(params={**NEVER_EOD, "min_opportunity_score": 0, "min_seasonality_edge_pct": 100.0})
    df = _uptrend_1h_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(df, regime, float(df["close"].iloc[-1]))

    signal = strategy.generate_signal(ctx)

    assert signal.action != "BUY"
    assert any("Bloqueado" in r for r in signal.reasons)


def test_no_trade_at_or_after_the_eod_flatten_hour():
    strategy = DayTradingStrategy(params={"eod_flatten_hour_utc": 0, "min_opportunity_score": 0, "min_seasonality_edge_pct": -1000.0})
    df = _uptrend_1h_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(df, regime, float(df["close"].iloc[-1]))

    signal = strategy.generate_signal(ctx)

    assert signal.action == "NO_TRADE"
    assert any("cierre de fin de día" in r.lower() for r in signal.reasons)


def test_no_trade_when_too_close_to_the_eod_hour_even_if_not_reached_yet():
    """A trade opened with only an hour of runway left gets force-closed
    almost immediately regardless of how it's doing - this buffer exists
    specifically to stop that, separate from the hard cutoff at the EOD
    hour itself."""
    df = _uptrend_1h_df()
    last_hour = df.index[-1].hour
    strategy = DayTradingStrategy(params={
        "eod_flatten_hour_utc": last_hour + 2, "min_hours_before_eod_entry": 4,
        "min_opportunity_score": 0, "min_seasonality_edge_pct": -1000.0,
    })
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(df, regime, float(df["close"].iloc[-1]))

    signal = strategy.generate_signal(ctx)

    assert signal.action == "NO_TRADE"
    assert any("muy cerca del cierre" in r.lower() for r in signal.reasons)


def test_no_trade_when_net_profit_after_costs_does_not_clear_the_gate():
    strategy = DayTradingStrategy(params={**NEVER_EOD, "min_opportunity_score": 0, "atr_stop_multiplier": 0.01, "take_profit_rr": 0.01})
    df = _uptrend_1h_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(df, regime, float(df["close"].iloc[-1]))
    ctx.min_expected_net_profit_pct = 5.0
    ctx.taker_fee_pct = 0.1
    ctx.default_slippage_pct = 0.05

    signal = strategy.generate_signal(ctx)

    assert signal.action == "NO_TRADE"


def test_deterioration_exit_flattens_at_or_after_the_eod_hour_before_anything_else():
    strategy = DayTradingStrategy(params={"eod_flatten_hour_utc": 0})
    df = _uptrend_1h_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(
        df, regime, float(df["close"].iloc[-1]),
        open_position=OpenPositionView(entry_price=99, quantity=1, stop_loss=95, take_profit=1000, trailing_stop_pct=None, highest_price_since_entry=100, opened_at=None),
    )

    should_exit, reason = strategy.should_exit_on_deterioration(ctx)

    assert should_exit is True
    assert "fin de día" in reason.lower()


def test_deterioration_exit_does_nothing_without_an_open_position():
    strategy = DayTradingStrategy(params={"eod_flatten_hour_utc": 0})
    df = _uptrend_1h_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(df, regime, float(df["close"].iloc[-1]), open_position=None)

    should_exit, reason = strategy.should_exit_on_deterioration(ctx)

    assert should_exit is False
    assert reason is None


def test_deterioration_exit_on_trend_reversal_when_not_eod():
    strategy = DayTradingStrategy(params=NEVER_EOD)
    n = 80
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    # Uptrend for most of the window, then a sharp reversal at the end so
    # the fast EMA crosses back below the slow EMA - a real deterioration,
    # not just noise.
    closes = [100.0 * (1 + 0.003 * i) for i in range(n - 10)]
    closes += [closes[-1] * (1 - 0.01 * i) for i in range(1, 11)]
    df = pd.DataFrame(
        {
            "open": [c * 0.999 for c in closes], "high": [c * 1.002 for c in closes],
            "low": [c * 0.997 for c in closes], "close": closes,
            "volume": [1000.0] * n,
        },
        index=idx,
    )
    regime = RegimeReading(trend=TrendRegime.DOWNTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(
        df, regime, float(df["close"].iloc[-1]),
        open_position=OpenPositionView(entry_price=closes[0], quantity=1, stop_loss=0, take_profit=1e9, trailing_stop_pct=None, highest_price_since_entry=max(closes), opened_at=None),
    )

    should_exit, reason = strategy.should_exit_on_deterioration(ctx)

    assert should_exit is True
    assert reason is not None
