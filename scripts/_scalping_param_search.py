"""One-off analysis script (not part of the app): backtests ScalpingStrategy
across every symbol with enough 5m history, under several take_profit/
stop_loss configurations, to find one with a real edge instead of guessing.
Run via `docker exec binmarket-backend-1 python scripts/_scalping_param_search.py`.
"""
from __future__ import annotations

from sqlalchemy import func, select

from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import Candle, Symbol
from binmarket_shared.trading.backtest.engine import run_backtest
from binmarket_shared.trading.strategies.scalping import ScalpingStrategy

CANDIDATES = [
    ("current (TP0.5/SL0.6)", {"take_profit_pct": 0.5, "stop_loss_pct": 0.6}),
    ("TP0.6/SL0.5", {"take_profit_pct": 0.6, "stop_loss_pct": 0.5}),
    ("TP0.8/SL0.5", {"take_profit_pct": 0.8, "stop_loss_pct": 0.5}),
    ("TP1.0/SL0.5", {"take_profit_pct": 1.0, "stop_loss_pct": 0.5}),
    ("TP1.2/SL0.6", {"take_profit_pct": 1.2, "stop_loss_pct": 0.6}),
    ("TP1.5/SL0.7", {"take_profit_pct": 1.5, "stop_loss_pct": 0.7}),
]

MIN_CANDLES = 300


def main() -> None:
    with session_scope() as db:
        symbol_rows = {
            row.symbol: row
            for row in db.query(Symbol).filter(Symbol.quote_asset == "USDT").all()
        }
        counts = db.execute(
            select(Candle.symbol, func.count(Candle.id))
            .where(Candle.timeframe == "5m")
            .group_by(Candle.symbol)
        ).all()
        symbols = [s for s, n in counts if n >= MIN_CANDLES and s in symbol_rows]
        print(f"Backtesting {len(symbols)} symbols with >= {MIN_CANDLES} 5m candles: {symbols}\n")

        dataframes = {}
        for symbol in symbols:
            from binmarket_shared.trading.engine_loop import load_candle_dataframe
            dataframes[symbol] = load_candle_dataframe(db, symbol, "5m", limit=5000)

        for label, params in CANDIDATES:
            total_trades = total_wins = total_losses = 0
            total_pnl = 0.0
            symbols_profitable = 0
            symbols_tested = 0
            for symbol in symbols:
                df = dataframes[symbol]
                row = symbol_rows[symbol]
                filters = SymbolFilters(symbol, row.price_tick_size, row.lot_step_size, row.min_qty, row.max_qty, row.min_notional) if row.lot_step_size else None
                strategy = ScalpingStrategy(params)
                result = run_backtest(
                    df, strategy, symbol, "5m", initial_capital=1000.0,
                    fee_pct=0.1, slippage_pct=0.05, risk_per_trade_pct=1.0,
                    max_position_size_pct=20.0, max_total_exposure_pct=50.0,
                    min_expected_net_profit_pct=0.15, symbol_filters=filters,
                )
                if result.total_trades == 0:
                    continue
                symbols_tested += 1
                pnl = result.final_capital - result.initial_capital
                total_pnl += pnl
                total_trades += result.total_trades
                total_wins += result.winning_trades
                total_losses += result.losing_trades
                if pnl > 0:
                    symbols_profitable += 1

            win_rate = total_wins / total_trades * 100 if total_trades else 0
            print(
                f"{label:24s} | symbols={symbols_tested:2d} profitable={symbols_profitable:2d} | "
                f"trades={total_trades:4d} win_rate={win_rate:5.1f}% | total_pnl=${total_pnl:8.3f}"
            )


if __name__ == "__main__":
    main()
