from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.binance_factory import get_binance_client_for_mode
from app.core.deps import get_app_settings, get_current_user, get_db
from app.redis_client import redis_client
from binmarket_shared.db.models import AppSettings, PortfolioSnapshot, Position, PositionStatus, User
from binmarket_shared.redis_keys import ticker_key
from binmarket_shared.trading.execution import get_execution_provider
from binmarket_shared.trading.risk.manager import RiskManager

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class PortfolioSummaryResponse(BaseModel):
    mode: str
    total_equity: float
    cash_balance: float
    invested_value: float
    pnl_today: float
    pnl_week: float
    pnl_month: float
    pnl_total: float
    roi_pct: float
    win_rate_pct: float
    drawdown_pct: float
    open_positions_count: int


class SnapshotResponse(BaseModel):
    taken_at: datetime
    total_equity: float
    pnl_total: float
    roi_pct: float
    drawdown_pct: float

    class Config:
        from_attributes = True


class SymbolBreakdownResponse(BaseModel):
    symbol: str
    exposure_value: float
    exposure_pct: float
    unrealized_pnl: float | None
    realized_pnl_today: float


def _provider_for(app_settings: AppSettings, db: Session):
    if app_settings.mode.value == "PAPER":
        return get_execution_provider("PAPER", db=db)
    client = get_binance_client_for_mode(app_settings.mode)
    return get_execution_provider(app_settings.mode.value, binance_client=client)


def _current_price(symbol: str, fallback: float) -> float:
    raw = redis_client.get(ticker_key(symbol))
    return float(json.loads(raw)["price"]) if raw else fallback


@router.get("/summary", response_model=PortfolioSummaryResponse)
def portfolio_summary(
    db: Session = Depends(get_db), app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user)
) -> PortfolioSummaryResponse:
    risk_manager = RiskManager(db, app_settings)
    provider = _provider_for(app_settings, db)

    cash = provider.get_available_balance("USDT")
    open_positions = risk_manager.open_positions(app_settings.mode)
    invested_value_mtm = sum(_current_price(p.symbol, p.entry_price) * p.quantity for p in open_positions)
    total_equity = cash + invested_value_mtm

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    pnl_today = risk_manager.realized_pnl_since(app_settings.mode, today_start)
    pnl_week = risk_manager.weekly_realized_pnl(app_settings.mode)
    pnl_month = risk_manager.realized_pnl_since(app_settings.mode, month_start)

    closed_all = db.query(Position).filter(Position.mode == app_settings.mode, Position.status == PositionStatus.CLOSED).all()
    pnl_total = sum(p.realized_pnl for p in closed_all)
    wins = sum(1 for p in closed_all if p.realized_pnl > 0)
    win_rate = (wins / len(closed_all) * 100) if closed_all else 0.0

    starting_capital = app_settings.paper_starting_balance_usdt if app_settings.mode.value == "PAPER" else max(total_equity - pnl_total, 1.0)
    roi_pct = (pnl_total / starting_capital * 100) if starting_capital else 0.0

    latest_snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.mode == app_settings.mode)
        .order_by(PortfolioSnapshot.taken_at.desc())
        .limit(500)
        .all()
    )
    peak = max([s.total_equity for s in latest_snapshots] + [total_equity], default=total_equity)
    drawdown_pct = ((total_equity - peak) / peak * 100) if peak else 0.0

    return PortfolioSummaryResponse(
        mode=app_settings.mode.value, total_equity=total_equity, cash_balance=cash, invested_value=invested_value_mtm,
        pnl_today=pnl_today, pnl_week=pnl_week, pnl_month=pnl_month, pnl_total=pnl_total, roi_pct=roi_pct,
        win_rate_pct=win_rate, drawdown_pct=drawdown_pct, open_positions_count=len(open_positions),
    )


@router.get("/snapshots", response_model=list[SnapshotResponse])
def portfolio_snapshots(
    days: int = Query(30, le=365), db: Session = Depends(get_db),
    app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user),
) -> list[PortfolioSnapshot]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.mode == app_settings.mode, PortfolioSnapshot.taken_at >= since)
        .order_by(PortfolioSnapshot.taken_at.asc())
        .all()
    )


@router.get("/breakdown", response_model=list[SymbolBreakdownResponse])
def portfolio_breakdown(
    db: Session = Depends(get_db), app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user)
) -> list[SymbolBreakdownResponse]:
    risk_manager = RiskManager(db, app_settings)
    open_positions = risk_manager.open_positions(app_settings.mode)
    total_exposure = sum(p.entry_price * p.quantity for p in open_positions) or 1.0

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    closed_today = (
        db.query(Position)
        .filter(Position.mode == app_settings.mode, Position.status == PositionStatus.CLOSED, Position.closed_at >= today_start)
        .all()
    )

    results = []
    for p in open_positions:
        current_price = _current_price(p.symbol, p.entry_price)
        exposure_value = p.entry_price * p.quantity
        results.append(SymbolBreakdownResponse(
            symbol=p.symbol, exposure_value=exposure_value, exposure_pct=exposure_value / total_exposure * 100,
            unrealized_pnl=(current_price - p.entry_price) * p.quantity,
            realized_pnl_today=sum(c.realized_pnl for c in closed_today if c.symbol == p.symbol),
        ))
    return results
