"""Basic walk-forward validation (section 16 of the spec).

Splits the requested date range into N consecutive, non-overlapping
out-of-sample windows and runs the (fixed-parameter) backtest engine on each
one independently, each with its own leading warm-up slice so indicators are
valid from the first counted bar. This is intentionally the simplified
version documented in docs/architecture.md: it proves a strategy holds up
across several distinct periods rather than being curve-fit to one, but it
does not re-optimize parameters per window (that would require the
parameter-search tooling from section 30, which is a separate, simpler
grid-search feature). A strategy whose metrics collapse from one window to
the next is a strong signal of overfitting to the earlier data.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.trading.strategies.base import BaseStrategy

from .engine import BacktestResult, run_backtest


@dataclass
class WalkForwardWindowResult:
    window_index: int
    start: str
    end: str
    result: BacktestResult


def run_walk_forward(
    df: pd.DataFrame,
    strategy: BaseStrategy,
    symbol: str,
    timeframe: str,
    n_windows: int = 4,
    initial_capital: float = 10_000.0,
    fee_pct: float = 0.1,
    slippage_pct: float = 0.05,
    risk_per_trade_pct: float = 1.0,
    max_position_size_pct: float = 20.0,
    max_total_exposure_pct: float = 50.0,
    min_expected_net_profit_pct: float = 0.15,
    symbol_filters: SymbolFilters | None = None,
) -> list[WalkForwardWindowResult]:
    n_windows = max(2, n_windows)
    total_len = len(df)
    warmup = strategy.min_bars_required
    usable_len = total_len - warmup
    if usable_len <= n_windows:
        raise ValueError("Not enough data for the requested number of walk-forward windows")

    window_size = usable_len // n_windows
    results: list[WalkForwardWindowResult] = []

    for w in range(n_windows):
        segment_start = warmup + w * window_size
        segment_end = total_len if w == n_windows - 1 else warmup + (w + 1) * window_size
        slice_start = max(0, segment_start - warmup)
        data_slice = df.iloc[slice_start:segment_end]

        result = run_backtest(
            data_slice, strategy, symbol, timeframe, initial_capital, fee_pct, slippage_pct,
            risk_per_trade_pct, max_position_size_pct, max_total_exposure_pct,
            min_expected_net_profit_pct, symbol_filters,
        )
        results.append(WalkForwardWindowResult(
            window_index=w,
            start=str(data_slice.index[0]) if len(data_slice) else "",
            end=str(data_slice.index[-1]) if len(data_slice) else "",
            result=result,
        ))

    return results
