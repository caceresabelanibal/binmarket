"""Periodic portfolio/balance snapshots so the dashboard's equity curve and
drawdown have history to draw from (sections 19/20/21). Runs inside the
trading-engine loop rather than a separate scheduler service — see
docs/architecture.md for why a 6th service wasn't warranted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from binmarket_shared.db.models import AppSettings, BalanceSnapshot, PortfolioSnapshot, PositionStatus, TradingMode
from binmarket_shared.trading.execution.base import ExecutionProvider
from binmarket_shared.trading.risk.manager import RiskManager

logger = logging.getLogger("binmarket.trading_engine.snapshots")


def take_portfolio_snapshot(db: Session, settings: AppSettings, provider: ExecutionProvider, current_price_fn) -> None:
    risk_manager = RiskManager(db, settings)
    mode = settings.mode

    cash = provider.get_available_balance("USDT")
    open_positions = risk_manager.open_positions(mode)
    invested_value = sum(current_price_fn(p.symbol, p.entry_price) * p.quantity for p in open_positions)
    total_equity = cash + invested_value

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    pnl_today = risk_manager.realized_pnl_since(mode, today_start)
    pnl_week = risk_manager.weekly_realized_pnl(mode)
    pnl_month = risk_manager.realized_pnl_since(mode, month_start)

    from binmarket_shared.db.models import Position

    closed_all = db.query(Position).filter(Position.mode == mode, Position.status == PositionStatus.CLOSED).all()
    pnl_total = sum(p.realized_pnl for p in closed_all)

    starting_capital = settings.paper_starting_balance_usdt if mode == TradingMode.PAPER else max(total_equity - pnl_total, 1.0)
    roi_pct = (pnl_total / starting_capital * 100) if starting_capital else 0.0

    previous_peak = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.mode == mode).order_by(
        PortfolioSnapshot.total_equity.desc()
    ).first()
    peak = max(total_equity, previous_peak.total_equity if previous_peak else total_equity)
    drawdown_pct = ((total_equity - peak) / peak * 100) if peak else 0.0

    db.add(PortfolioSnapshot(
        mode=mode, total_equity=total_equity, cash_balance=cash, invested_value=invested_value,
        pnl_today=pnl_today, pnl_week=pnl_week, pnl_month=pnl_month, pnl_total=pnl_total,
        roi_pct=roi_pct, drawdown_pct=drawdown_pct,
    ))


def take_balance_snapshot(db: Session, settings: AppSettings, binance_client) -> None:
    """Only meaningful for TESTNET/LIVE, where there is a real Binance
    account to read balances from; PAPER's equity is fully captured by the
    portfolio snapshot above."""
    if settings.mode == TradingMode.PAPER or binance_client is None:
        return
    try:
        account = binance_client.get_account()
    except Exception:
        logger.exception("Failed to fetch account balances for balance snapshot")
        return
    for b in account.get("balances", []):
        free, locked = float(b["free"]), float(b["locked"])
        if free or locked:
            db.add(BalanceSnapshot(mode=settings.mode, asset=b["asset"], free=free, locked=locked))
