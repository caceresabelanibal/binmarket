from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.binance_factory import get_binance_client_for_mode
from app.core.deps import get_app_settings, get_current_user, get_db
from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.binance.errors import BinanceAPIError, BinanceConnectivityError
from binmarket_shared.binance.valuation import compute_account_total_value
from binmarket_shared.config import settings as env_settings
from binmarket_shared.db.models import AppSettings, Position, PositionStatus, RealAccountSnapshot, User
from binmarket_shared.trading.execution import get_execution_provider

router = APIRouter(prefix="/api/binance", tags=["binance"])


class RealAccountHistoryEntry(BaseModel):
    id: int
    taken_at: datetime
    total_usdt: float
    total_ars: float | None
    usdt_ars_rate: float | None

    class Config:
        from_attributes = True


class RealAccountHistoryResponse(BaseModel):
    items: list[RealAccountHistoryEntry]
    total: int
    page: int
    page_size: int


class ConnectivityResponse(BaseModel):
    ping: bool
    server_time: int | None
    account_reachable: bool
    error: str | None
    environment: str
    masked_api_key: str


@router.post("/test-connectivity", response_model=ConnectivityResponse)
def test_connectivity(app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user)) -> dict:
    client = get_binance_client_for_mode(app_settings.mode)
    result = client.test_connectivity()
    client.close()
    return {**result, "environment": client.environment, "masked_api_key": env_settings.binance_masked_key}


@router.get("/account")
def get_account(app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user)) -> dict:
    client = get_binance_client_for_mode(app_settings.mode)
    try:
        account = client.get_account()
    except (BinanceAPIError, BinanceConnectivityError) as exc:
        return {"error": str(exc)}
    finally:
        client.close()

    balances = [b for b in account.get("balances", []) if float(b["free"]) > 0 or float(b["locked"]) > 0]
    can_withdraw = bool(account.get("canWithdraw", False))
    warnings = []
    if can_withdraw:
        warnings.append(
            "ADVERTENCIA: esta API Key tiene el permiso de retiros (withdrawals) habilitado. "
            "Nunca se debe usar una key con este permiso para trading automático; deshabilítalo en Binance."
        )
    return {
        "account_type": account.get("accountType"),
        "can_trade": account.get("canTrade"),
        "can_withdraw": can_withdraw,
        "balances": balances,
        "warnings": warnings,
    }


@router.get("/account/total-value")
def account_total_value(_: User = Depends(get_current_user)) -> dict:
    """Total value of every asset actually held in the Binance **spot**
    wallet, converted to ARS via Binance's own USDTARS market — independent
    of the app's current trading mode (PAPER/TESTNET/LIVE), because this is
    about the user's real account, not the simulator. Always queries
    production, since that's where a real account lives.

    Does not include Binance Earn/staking/savings balances — those live in a
    separate wallet the `/account` endpoint doesn't see either.
    """
    client = BinanceClient(env_settings.binance_api_key, env_settings.binance_api_secret, environment="production")
    try:
        return compute_account_total_value(client)
    finally:
        client.close()


@router.get("/account/total-value/history", response_model=RealAccountHistoryResponse)
def account_total_value_history(
    page: int = 1, page_size: int = 10,
    db: Session = Depends(get_db), _: User = Depends(get_current_user),
) -> RealAccountHistoryResponse:
    """Paginated history of the "Capital real" card, newest first — snapshots
    are taken every 6h by the trading-engine (see
    trading-engine/app/snapshots.py::take_real_account_snapshot) and pruned
    to the last 30 days there, independent of trading mode."""
    page = max(page, 1)
    # 30 days of retention at a 6h cadence is up to 120 snapshots - the trend
    # chart on the Dashboard fetches the whole window in one call, so the cap
    # needs to clear that, not just the paginated table's page size.
    page_size = max(1, min(page_size, 150))
    query = db.query(RealAccountSnapshot).order_by(RealAccountSnapshot.taken_at.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return RealAccountHistoryResponse(items=rows, total=total, page=page, page_size=page_size)


class TradeWindowStats(BaseModel):
    winning_trades: int
    losing_trades: int
    winning_amount_usdt: float
    losing_amount_usdt: float
    net_pnl_usdt: float


class TradeStatsResponse(BaseModel):
    operable_capital_usdt: float
    last_24h: TradeWindowStats
    last_7d: TradeWindowStats
    month_to_date: TradeWindowStats


def _trade_window_stats(db: Session, mode, start: datetime, end: datetime) -> TradeWindowStats:
    closed = (
        db.query(Position)
        .filter(
            Position.mode == mode, Position.status == PositionStatus.CLOSED,
            Position.closed_at >= start, Position.closed_at <= end,
        )
        .all()
    )
    wins = [p for p in closed if p.realized_pnl > 0]
    losses = [p for p in closed if p.realized_pnl <= 0]
    return TradeWindowStats(
        winning_trades=len(wins),
        losing_trades=len(losses),
        winning_amount_usdt=sum(p.realized_pnl for p in wins),
        losing_amount_usdt=sum(p.realized_pnl for p in losses),
        net_pnl_usdt=sum(p.realized_pnl for p in closed),
    )


@router.get("/account/trade-stats", response_model=TradeStatsResponse)
def trade_stats(
    app_settings: AppSettings = Depends(get_app_settings),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TradeStatsResponse:
    """"Capital operable" (the real spendable balance an execution provider
    would actually see right now - free USDT, not the total account value
    shown by "Capital real", which also counts non-spendable holdings like
    open positions, ARS, or dust in other assets) plus win/loss counts and
    accumulated USDT for the last 24h, last 7 days, and month-to-date -
    all scoped to the currently active trading mode, matching what
    "Capital operable" itself represents.
    """
    binance_client = None
    if app_settings.mode.value != "PAPER":
        binance_client = get_binance_client_for_mode(app_settings.mode)
    try:
        provider = get_execution_provider(app_settings.mode.value, db=db, binance_client=binance_client)
        operable_capital = provider.get_available_balance("USDT")
    finally:
        if binance_client is not None:
            binance_client.close()

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    return TradeStatsResponse(
        operable_capital_usdt=operable_capital,
        last_24h=_trade_window_stats(db, app_settings.mode, now - timedelta(hours=24), now),
        last_7d=_trade_window_stats(db, app_settings.mode, now - timedelta(days=7), now),
        month_to_date=_trade_window_stats(db, app_settings.mode, month_start, now),
    )


@router.get("/exchange-info")
def get_exchange_info(
    symbol: str | None = None,
    app_settings: AppSettings = Depends(get_app_settings),
    _: User = Depends(get_current_user),
) -> dict:
    client = get_binance_client_for_mode(app_settings.mode)
    try:
        return client.get_exchange_info(symbol)
    finally:
        client.close()
