from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.binance_factory import get_binance_client_for_mode
from app.core.deps import get_app_settings, get_current_user, get_db
from binmarket_shared.db.models import AppSettings, RiskEvent, RiskSeverity, User
from binmarket_shared.trading.execution import get_execution_provider
from binmarket_shared.trading.risk.manager import RiskManager

router = APIRouter(prefix="/api/risk", tags=["risk"])


class RiskEventResponse(BaseModel):
    id: int
    event_type: str
    symbol: str | None
    severity: RiskSeverity
    details: dict
    occurred_at: datetime

    class Config:
        from_attributes = True


class RiskStateResponse(BaseModel):
    mode: str
    available_capital: float
    open_positions_count: int
    total_exposure_value: float
    total_exposure_pct: float
    daily_pnl: float
    daily_pnl_pct: float
    weekly_pnl: float
    weekly_pnl_pct: float
    consecutive_losing_trades: int
    emergency_stop_active: bool
    emergency_stop_reason: str | None
    limits: dict


@router.get("/state", response_model=RiskStateResponse)
def get_risk_state(
    db: Session = Depends(get_db), app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user)
) -> RiskStateResponse:
    risk_manager = RiskManager(db, app_settings)

    if app_settings.mode.value == "PAPER":
        provider = get_execution_provider("PAPER", db=db)
    else:
        client = get_binance_client_for_mode(app_settings.mode)
        provider = get_execution_provider(app_settings.mode.value, binance_client=client)
    available_capital = provider.get_available_balance("USDT") or 1.0

    exposure = risk_manager.total_exposure_value(app_settings.mode)
    daily_pnl = risk_manager.daily_realized_pnl(app_settings.mode)
    weekly_pnl = risk_manager.weekly_realized_pnl(app_settings.mode)

    return RiskStateResponse(
        mode=app_settings.mode.value,
        available_capital=available_capital,
        open_positions_count=risk_manager.open_positions_count(app_settings.mode),
        total_exposure_value=exposure,
        total_exposure_pct=exposure / available_capital * 100,
        daily_pnl=daily_pnl,
        daily_pnl_pct=daily_pnl / available_capital * 100,
        weekly_pnl=weekly_pnl,
        weekly_pnl_pct=weekly_pnl / available_capital * 100,
        consecutive_losing_trades=risk_manager.consecutive_losing_trades(app_settings.mode),
        emergency_stop_active=app_settings.emergency_stop_active,
        emergency_stop_reason=app_settings.emergency_stop_reason,
        limits={
            "max_risk_per_trade_pct": app_settings.max_risk_per_trade_pct,
            "max_total_exposure_pct": app_settings.max_total_exposure_pct,
            "max_position_size_pct": app_settings.max_position_size_pct,
            "max_daily_loss_pct": app_settings.max_daily_loss_pct,
            "max_weekly_loss_pct": app_settings.max_weekly_loss_pct,
            "max_open_positions": app_settings.max_open_positions,
            "max_consecutive_losses": app_settings.max_consecutive_losses,
        },
    )


@router.get("/events", response_model=list[RiskEventResponse])
def list_risk_events(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[RiskEvent]:
    return db.query(RiskEvent).order_by(RiskEvent.occurred_at.desc()).limit(200).all()


@router.post("/emergency-stop/trigger")
def trigger_emergency_stop(
    reason: str = "Activado manualmente desde el panel de riesgo",
    db: Session = Depends(get_db),
    app_settings: AppSettings = Depends(get_app_settings),
    _: User = Depends(get_current_user),
) -> dict:
    RiskManager(db, app_settings).trigger_emergency_stop(reason)
    db.commit()
    return {"status": "emergency_stop_active"}
