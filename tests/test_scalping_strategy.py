from __future__ import annotations

import pandas as pd
import pytest

from binmarket_shared.quant.regime import RegimeReading, TrendRegime, VolatilityRegime
from binmarket_shared.trading.strategies.base import StrategyContext
from binmarket_shared.trading.strategies.registry import STRATEGY_REGISTRY, get_strategy
from binmarket_shared.trading.strategies.scalping import ScalpingStrategy


def _uptrend_5m_df(n=60, start_price=100.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    closes = [start_price * (1 + 0.001 * i) for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes, "high": [c * 1.0005 for c in closes], "low": [c * 0.9995 for c in closes],
            "close": closes, "volume": [1000.0 + i * 5 for i in range(n)],
        },
        index=idx,
    )


def _ctx(df, regime, current_price, open_position=None):
    return StrategyContext(
        df=df, symbol="TESTUSDT", timeframe="5m", regime=regime, current_price=current_price,
        best_bid=current_price, best_ask=current_price, available_capital=1000.0,
        current_total_exposure_value=0.0, max_total_exposure_pct=50.0, max_position_size_pct=20.0,
        risk_per_trade_pct=1.0, taker_fee_pct=0.1, default_slippage_pct=0.05,
        min_expected_net_profit_pct=0.05, open_position=open_position,
    )


def test_scalping_is_registered():
    assert "scalping" in STRATEGY_REGISTRY
    assert get_strategy("scalping") is not None


def test_preferred_timeframe_is_5m_not_1h():
    assert ScalpingStrategy.preferred_timeframe == "5m"


def test_needs_far_fewer_bars_than_the_1h_strategies():
    assert ScalpingStrategy().min_bars_required <= 30


@pytest.mark.parametrize(
    "volatility,expected",
    [
        (VolatilityRegime.LOW, False),
        (VolatilityRegime.NORMAL, True),
        (VolatilityRegime.HIGH, True),
        (VolatilityRegime.EXTREME, False),
    ],
)
def test_eligibility_requires_normal_or_high_volatility(volatility, expected):
    strategy = ScalpingStrategy()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=volatility, adx_value=25, volatility_pct=1.0)
    assert strategy.is_regime_eligible(regime) is expected


def test_take_profit_and_stop_loss_are_a_small_configurable_pct_of_entry():
    strategy = ScalpingStrategy(params={"take_profit_pct": 0.4, "stop_loss_pct": 0.6, "min_opportunity_score": 0})
    df = _uptrend_5m_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    entry_price = float(df["close"].iloc[-1])
    ctx = _ctx(df, regime, entry_price)

    signal = strategy.generate_signal(ctx)

    assert signal.take_profit == pytest.approx(entry_price * 1.004, rel=1e-6)
    assert signal.stop_loss == pytest.approx(entry_price * 0.994, rel=1e-6)


def test_never_buys_again_while_a_position_is_already_open():
    strategy = ScalpingStrategy()
    df = _uptrend_5m_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    from binmarket_shared.trading.strategies.base import OpenPositionView

    ctx = _ctx(
        df, regime, float(df["close"].iloc[-1]),
        open_position=OpenPositionView(entry_price=99, quantity=1, stop_loss=95, take_profit=101, trailing_stop_pct=None, highest_price_since_entry=100, opened_at=None),
    )
    signal = strategy.generate_signal(ctx)
    assert signal.action == "HOLD"


def test_no_trade_when_net_profit_after_costs_does_not_clear_the_gate():
    """Even a tiny scalp target must still clear the same profitability gate
    every other strategy respects — this is what stops "ganar poco" from
    quietly becoming "pierdo poco en comisiones cada vez"."""
    strategy = ScalpingStrategy(params={"take_profit_pct": 0.05, "min_opportunity_score": 0})  # unrealistically tiny target
    df = _uptrend_5m_df()
    regime = RegimeReading(trend=TrendRegime.UPTREND, volatility=VolatilityRegime.NORMAL, adx_value=25, volatility_pct=1.0)
    ctx = _ctx(df, regime, float(df["close"].iloc[-1]))
    ctx.min_expected_net_profit_pct = 0.15
    ctx.taker_fee_pct = 0.1
    ctx.default_slippage_pct = 0.05

    signal = strategy.generate_signal(ctx)

    assert signal.action == "NO_TRADE"
    assert any("no alcanza" in r for r in signal.reasons)
