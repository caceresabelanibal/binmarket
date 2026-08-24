"""Bar-by-bar backtest engine (section 15 of the spec).

Deliberately walks the data one bar at a time and only ever exposes
`df.iloc[:i+1]` (past and current bar) to the strategy, so a strategy cannot
accidentally see future bars — the same `generate_signal` used live is used
here unchanged, which is what makes the backtest a genuine rehearsal instead
of a curve-fit exercise. Fees and slippage are charged on every fill, exactly
like the Paper/Testnet/Live execution providers do.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.quant.costs import apply_slippage
from binmarket_shared.quant.position_sizing import calculate_position_size
from binmarket_shared.quant.regime import classify_regime
from binmarket_shared.trading.strategies.base import BaseStrategy, OpenPositionView, StrategyContext


@dataclass
class BacktestTradeRecord:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees_paid: float
    exit_reason: str


@dataclass
class BacktestResult:
    initial_capital: float
    final_capital: float
    roi_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float | None
    sharpe_ratio: float | None
    max_drawdown_pct: float
    best_trade_pct: float | None
    worst_trade_pct: float | None
    avg_trade_duration_bars: float
    equity_curve: list[dict] = field(default_factory=list)
    trades: list[BacktestTradeRecord] = field(default_factory=list)


def _compute_metrics(
    initial_capital: float, cash_history: list[tuple], trades: list[BacktestTradeRecord]
) -> BacktestResult:
    equity_curve = [{"t": t.isoformat(), "equity": eq} for t, eq in cash_history]
    equities = np.array([eq for _, eq in cash_history], dtype=float)
    final_capital = equities[-1] if len(equities) else initial_capital

    running_max = np.maximum.accumulate(equities) if len(equities) else np.array([initial_capital])
    drawdowns = np.where(running_max > 0, (equities - running_max) / running_max * 100, 0.0)
    max_drawdown_pct = float(drawdowns.min()) if len(drawdowns) else 0.0

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (None if not wins else float("inf"))

    bar_returns = np.diff(equities) / equities[:-1] if len(equities) > 1 else np.array([])
    bar_returns = bar_returns[np.isfinite(bar_returns)]
    sharpe_ratio = None
    if len(bar_returns) > 1 and bar_returns.std() > 0:
        sharpe_ratio = float(bar_returns.mean() / bar_returns.std() * np.sqrt(len(bar_returns)))

    pct_list = [t.pnl_pct for t in trades]

    return BacktestResult(
        initial_capital=initial_capital,
        final_capital=float(final_capital),
        roi_pct=((final_capital - initial_capital) / initial_capital * 100) if initial_capital else 0.0,
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate_pct=(len(wins) / len(trades) * 100) if trades else 0.0,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=max_drawdown_pct,
        best_trade_pct=max(pct_list) if pct_list else None,
        worst_trade_pct=min(pct_list) if pct_list else None,
        avg_trade_duration_bars=(
            sum((t.exit_time - t.entry_time).total_seconds() for t in trades) / len(trades) / 60
            if trades else 0.0
        ),
        equity_curve=equity_curve,
        trades=trades,
    )


def run_backtest(
    df: pd.DataFrame,
    strategy: BaseStrategy,
    symbol: str,
    timeframe: str,
    initial_capital: float = 10_000.0,
    fee_pct: float = 0.1,
    slippage_pct: float = 0.05,
    risk_per_trade_pct: float = 1.0,
    max_position_size_pct: float = 20.0,
    max_total_exposure_pct: float = 50.0,
    min_expected_net_profit_pct: float = 0.15,
    symbol_filters: SymbolFilters | None = None,
) -> BacktestResult:
    min_bars = strategy.min_bars_required
    if len(df) <= min_bars + 1:
        return _compute_metrics(initial_capital, [(df.index[0] if len(df) else pd.Timestamp.now(), initial_capital)], [])

    cash = initial_capital
    open_position: dict | None = None
    trades: list[BacktestTradeRecord] = []
    cash_history: list[tuple] = []

    for i in range(min_bars, len(df)):
        window = df.iloc[: i + 1]
        current_bar = window.iloc[-1]
        current_price = float(current_bar["close"])
        regime = classify_regime(window)

        if open_position is None:
            if strategy.is_regime_eligible(regime):
                ctx = StrategyContext(
                    df=window, symbol=symbol, timeframe=timeframe, regime=regime, current_price=current_price,
                    best_bid=current_price, best_ask=current_price, available_capital=cash,
                    current_total_exposure_value=0.0, max_total_exposure_pct=max_total_exposure_pct,
                    max_position_size_pct=max_position_size_pct, risk_per_trade_pct=risk_per_trade_pct,
                    taker_fee_pct=fee_pct, default_slippage_pct=slippage_pct,
                    min_expected_net_profit_pct=min_expected_net_profit_pct, symbol_filters=symbol_filters,
                    open_position=None,
                )
                signal = strategy.generate_signal(ctx)
                if signal.action == "BUY" and signal.stop_loss:
                    sizing = calculate_position_size(
                        cash, risk_per_trade_pct, signal.entry_price or current_price, signal.stop_loss,
                        0.0, max_total_exposure_pct, max_position_size_pct, symbol_filters,
                    )
                    if sizing.is_tradeable and sizing.quantity > 0:
                        fill_price = apply_slippage(signal.entry_price or current_price, "BUY", slippage_pct)
                        cost = fill_price * sizing.quantity
                        fee = cost * (fee_pct / 100)
                        if cost + fee <= cash:
                            cash -= cost + fee
                            open_position = {
                                "entry_price": fill_price,
                                "quantity": sizing.quantity,
                                "stop_loss": signal.stop_loss,
                                "take_profit": signal.take_profit,
                                "entry_time": window.index[-1],
                                "entry_fee": fee,
                                "highest_price": fill_price,
                            }
        else:
            low, high = float(current_bar["low"]), float(current_bar["high"])
            open_position["highest_price"] = max(open_position["highest_price"], high)

            exit_reason, exit_price = None, None
            if open_position["stop_loss"] and low <= open_position["stop_loss"]:
                exit_reason, exit_price = "stop_loss", open_position["stop_loss"]
            elif open_position["take_profit"] and high >= open_position["take_profit"]:
                exit_reason, exit_price = "take_profit", open_position["take_profit"]
            else:
                ctx_hold = StrategyContext(
                    df=window, symbol=symbol, timeframe=timeframe, regime=regime, current_price=current_price,
                    best_bid=current_price, best_ask=current_price, available_capital=cash,
                    current_total_exposure_value=open_position["entry_price"] * open_position["quantity"],
                    max_total_exposure_pct=max_total_exposure_pct, max_position_size_pct=max_position_size_pct,
                    risk_per_trade_pct=risk_per_trade_pct, taker_fee_pct=fee_pct,
                    default_slippage_pct=slippage_pct, min_expected_net_profit_pct=min_expected_net_profit_pct,
                    symbol_filters=symbol_filters,
                    open_position=OpenPositionView(
                        entry_price=open_position["entry_price"], quantity=open_position["quantity"],
                        stop_loss=open_position["stop_loss"], take_profit=open_position["take_profit"],
                        trailing_stop_pct=None, highest_price_since_entry=open_position["highest_price"],
                        opened_at=open_position["entry_time"],
                    ),
                )
                should_exit, reason = strategy.should_exit_on_deterioration(ctx_hold)
                if should_exit:
                    exit_reason, exit_price = reason, current_price

            if exit_reason:
                fill_price = apply_slippage(exit_price, "SELL", slippage_pct)
                proceeds = fill_price * open_position["quantity"]
                fee = proceeds * (fee_pct / 100)
                cash += proceeds - fee
                cost_basis = open_position["entry_price"] * open_position["quantity"] + open_position["entry_fee"]
                pnl = (proceeds - fee) - cost_basis
                trades.append(BacktestTradeRecord(
                    entry_time=open_position["entry_time"], exit_time=window.index[-1],
                    entry_price=open_position["entry_price"], exit_price=fill_price,
                    quantity=open_position["quantity"], pnl=pnl, pnl_pct=(pnl / cost_basis * 100) if cost_basis else 0.0,
                    fees_paid=fee + open_position["entry_fee"], exit_reason=exit_reason,
                ))
                open_position = None

        equity = cash + (open_position["quantity"] * current_price if open_position else 0.0)
        cash_history.append((window.index[-1], equity))

    if open_position is not None:
        last_price = float(df.iloc[-1]["close"])
        fill_price = apply_slippage(last_price, "SELL", slippage_pct)
        proceeds = fill_price * open_position["quantity"]
        fee = proceeds * (fee_pct / 100)
        cash += proceeds - fee
        cost_basis = open_position["entry_price"] * open_position["quantity"] + open_position["entry_fee"]
        pnl = (proceeds - fee) - cost_basis
        trades.append(BacktestTradeRecord(
            entry_time=open_position["entry_time"], exit_time=df.index[-1],
            entry_price=open_position["entry_price"], exit_price=fill_price, quantity=open_position["quantity"],
            pnl=pnl, pnl_pct=(pnl / cost_basis * 100) if cost_basis else 0.0,
            fees_paid=fee + open_position["entry_fee"], exit_reason="backtest_end",
        ))
        if cash_history:
            cash_history[-1] = (cash_history[-1][0], cash)

    return _compute_metrics(initial_capital, cash_history, trades)
