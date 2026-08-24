from __future__ import annotations

from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.db.models import Backtest, BacktestStatus, BacktestTrade, Candle, Symbol, User
from binmarket_shared.trading.backtest.engine import run_backtest
from binmarket_shared.trading.backtest.walk_forward import run_walk_forward
from binmarket_shared.trading.strategies.registry import get_strategy

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


class BacktestCreateRequest(BaseModel):
    name: str
    symbol: str
    timeframe: str
    strategy_name: str
    parameters: dict | None = None
    start_date: datetime
    end_date: datetime
    initial_capital: float = 10_000.0
    fee_pct: float = 0.1
    slippage_pct: float = 0.05
    risk_per_trade_pct: float = 1.0
    max_position_size_pct: float = 20.0
    max_total_exposure_pct: float = 50.0
    min_expected_net_profit_pct: float = 0.15
    is_walk_forward: bool = False
    walk_forward_windows: int = 4


class BacktestTradeResponse(BaseModel):
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees_paid: float
    exit_reason: str

    class Config:
        from_attributes = True


class BacktestResponse(BaseModel):
    id: str
    name: str
    symbol: str
    timeframe: str
    strategy_name: str
    parameters: dict
    start_date: datetime
    end_date: datetime
    initial_capital: float
    fee_pct: float
    slippage_pct: float
    is_walk_forward: bool
    status: BacktestStatus
    error_message: str | None
    results: dict
    equity_curve: list
    created_at: datetime
    finished_at: datetime | None

    class Config:
        from_attributes = True


def _load_df(db: Session, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
    rows = (
        db.query(Candle)
        .filter(Candle.symbol == symbol.upper(), Candle.timeframe == timeframe, Candle.open_time >= start, Candle.open_time <= end)
        .order_by(Candle.open_time.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return pd.DataFrame(
        {"open": [r.open for r in rows], "high": [r.high for r in rows], "low": [r.low for r in rows],
         "close": [r.close for r in rows], "volume": [r.volume for r in rows]},
        index=pd.DatetimeIndex([r.open_time for r in rows], name="open_time"),
    )


def _symbol_filters(db: Session, symbol: str) -> SymbolFilters | None:
    row = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).one_or_none()
    if row is None or row.lot_step_size <= 0:
        return None
    return SymbolFilters(symbol, row.price_tick_size, row.lot_step_size, row.min_qty, row.max_qty, row.min_notional)


@router.post("", response_model=BacktestResponse)
def create_backtest(
    payload: BacktestCreateRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Backtest:
    try:
        strategy = get_strategy(payload.strategy_name, payload.parameters)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    backtest = Backtest(
        name=payload.name, symbol=payload.symbol.upper(), timeframe=payload.timeframe,
        strategy_name=payload.strategy_name, parameters=strategy.params,
        start_date=payload.start_date, end_date=payload.end_date, initial_capital=payload.initial_capital,
        fee_pct=payload.fee_pct, slippage_pct=payload.slippage_pct, is_walk_forward=payload.is_walk_forward,
        status=BacktestStatus.RUNNING,
    )
    db.add(backtest)
    db.flush()

    df = _load_df(db, payload.symbol, payload.timeframe, payload.start_date, payload.end_date)
    if len(df) < strategy.min_bars_required + 5:
        backtest.status = BacktestStatus.FAILED
        backtest.error_message = (
            f"Datos históricos insuficientes ({len(df)} velas); sincronizar más historial antes de correr el backtest"
        )
        db.commit()
        db.refresh(backtest)
        return backtest

    symbol_filters = _symbol_filters(db, payload.symbol)

    try:
        if payload.is_walk_forward:
            windows = run_walk_forward(
                df, strategy, payload.symbol, payload.timeframe, payload.walk_forward_windows,
                payload.initial_capital, payload.fee_pct, payload.slippage_pct, payload.risk_per_trade_pct,
                payload.max_position_size_pct, payload.max_total_exposure_pct, payload.min_expected_net_profit_pct,
                symbol_filters,
            )
            backtest.results = {
                "windows": [
                    {"window_index": w.window_index, "start": w.start, "end": w.end, "roi_pct": w.result.roi_pct,
                     "win_rate_pct": w.result.win_rate_pct, "max_drawdown_pct": w.result.max_drawdown_pct,
                     "total_trades": w.result.total_trades, "sharpe_ratio": w.result.sharpe_ratio}
                    for w in windows
                ]
            }
            backtest.equity_curve = [pt for w in windows for pt in w.result.equity_curve]
            all_trades = [t for w in windows for t in w.result.trades]
        else:
            result = run_backtest(
                df, strategy, payload.symbol, payload.timeframe, payload.initial_capital, payload.fee_pct,
                payload.slippage_pct, payload.risk_per_trade_pct, payload.max_position_size_pct,
                payload.max_total_exposure_pct, payload.min_expected_net_profit_pct, symbol_filters,
            )
            backtest.results = {
                "initial_capital": result.initial_capital, "final_capital": result.final_capital,
                "roi_pct": result.roi_pct, "total_trades": result.total_trades, "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades, "win_rate_pct": result.win_rate_pct,
                "profit_factor": result.profit_factor, "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown_pct": result.max_drawdown_pct, "best_trade_pct": result.best_trade_pct,
                "worst_trade_pct": result.worst_trade_pct, "avg_trade_duration_minutes": result.avg_trade_duration_bars,
            }
            backtest.equity_curve = result.equity_curve
            all_trades = result.trades

        for t in all_trades:
            db.add(BacktestTrade(
                backtest_id=backtest.id, entry_time=t.entry_time, exit_time=t.exit_time, entry_price=t.entry_price,
                exit_price=t.exit_price, quantity=t.quantity, pnl=t.pnl, pnl_pct=t.pnl_pct, fees_paid=t.fees_paid,
                exit_reason=t.exit_reason,
            ))
        backtest.status = BacktestStatus.DONE
    except Exception as exc:  # noqa: BLE001
        backtest.status = BacktestStatus.FAILED
        backtest.error_message = str(exc)

    from datetime import datetime as _dt, timezone as _tz

    backtest.finished_at = _dt.now(_tz.utc)
    db.commit()
    db.refresh(backtest)
    return backtest


@router.get("", response_model=list[BacktestResponse])
def list_backtests(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Backtest]:
    return db.query(Backtest).order_by(Backtest.created_at.desc()).limit(100).all()


@router.get("/{backtest_id}", response_model=BacktestResponse)
def get_backtest(backtest_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Backtest:
    row = db.get(Backtest, backtest_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest no encontrado")
    return row


@router.get("/{backtest_id}/trades", response_model=list[BacktestTradeResponse])
def get_backtest_trades(backtest_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[BacktestTrade]:
    return db.query(BacktestTrade).filter(BacktestTrade.backtest_id == backtest_id).order_by(BacktestTrade.entry_time).all()
