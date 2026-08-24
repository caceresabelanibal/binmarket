import numpy as np
import pandas as pd
import pytest

from binmarket_shared.quant.regime import RegimeReading, TrendRegime, VolatilityRegime
from binmarket_shared.trading.backtest.engine import run_backtest
from binmarket_shared.trading.backtest.walk_forward import run_walk_forward
from binmarket_shared.trading.strategies.base import BaseStrategy, StrategyContext, StrategySignal
from binmarket_shared.quant.scoring import ScoreBreakdown


class AlwaysBuyOneBarStrategy(BaseStrategy):
    """Test double: buys the instant it's flat, sells one bar later. Lets us
    assert on cost handling and look-ahead without depending on real
    indicator thresholds ever firing."""

    name = "always_buy_one_bar"

    @property
    def min_bars_required(self) -> int:
        return 1  # test double: no real indicator warmup needed

    def is_regime_eligible(self, regime) -> bool:
        return True

    def generate_signal(self, ctx: StrategyContext) -> StrategySignal:
        scores = ScoreBreakdown(100, 100, 100, 100, 100, 100, ["test double"])
        if ctx.open_position is not None:
            return StrategySignal("HOLD", scores)
        entry = ctx.current_price
        return StrategySignal("BUY", scores, ["always buy"], entry_price=entry, stop_loss=entry * 0.9, take_profit=entry * 1.5)

    def should_exit_on_deterioration(self, ctx: StrategyContext):
        return (True, "one bar and done") if ctx.open_position is not None else (False, None)


def _flat_price_df(n=120, price=100.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": price, "high": price, "low": price, "close": price, "volume": 100.0}, index=idx)


def test_backtest_never_uses_future_bars_for_entries():
    """Rig the data so the ONLY bar with a favorable move is bar 80; a
    strategy using nothing but the current df.iloc[:i+1] window can't have
    traded on it before it happened."""
    df = _flat_price_df(120)
    df.loc[df.index[80], ["open", "high", "low", "close"]] = 500.0  # one-bar spike, then back to 100

    strategy = AlwaysBuyOneBarStrategy()
    result = run_backtest(df, strategy, "TESTUSDT", "1h", initial_capital=10_000, fee_pct=0, slippage_pct=0)

    # Trades must be roughly one-per-two-bars from the strategy's own logic,
    # and none of them can show a price at bar 80's spike unless entry_time
    # is actually at/after bar 80 — i.e. no trade "sees" the spike early.
    for trade in result.trades:
        if trade.entry_price == pytest.approx(500.0):
            assert trade.entry_time >= df.index[80]


def test_backtest_applies_fees_and_slippage():
    df = _flat_price_df(40)
    strategy = AlwaysBuyOneBarStrategy()

    free = run_backtest(df, strategy, "TESTUSDT", "1h", initial_capital=10_000, fee_pct=0, slippage_pct=0)
    costly = run_backtest(df, strategy, "TESTUSDT", "1h", initial_capital=10_000, fee_pct=0.5, slippage_pct=0.5)

    assert free.total_trades > 0
    assert costly.total_trades > 0
    # Same flat-price data, but fees+slippage must leave costly strictly
    # worse off than the frictionless run.
    assert costly.final_capital < free.final_capital
    assert all(t.fees_paid > 0 for t in costly.trades)
    assert all(t.fees_paid == 0 for t in free.trades)


def test_backtest_respects_max_position_size_cap():
    df = _flat_price_df(20)
    strategy = AlwaysBuyOneBarStrategy()
    result = run_backtest(
        df, strategy, "TESTUSDT", "1h", initial_capital=10_000, fee_pct=0.1, slippage_pct=0,
        risk_per_trade_pct=50, max_position_size_pct=10, max_total_exposure_pct=100,
    )
    for trade in result.trades:
        assert trade.entry_price * trade.quantity <= 10_000 * 0.10 + 1e-6


def test_walk_forward_produces_requested_number_of_windows():
    df = _flat_price_df(300)
    strategy = AlwaysBuyOneBarStrategy()
    windows = run_walk_forward(df, strategy, "TESTUSDT", "1h", n_windows=3, initial_capital=10_000)
    assert len(windows) == 3
    assert [w.window_index for w in windows] == [0, 1, 2]
