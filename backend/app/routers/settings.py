from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from binmarket_shared.db.models import AppSettings, BotEvent, BotEventAction, TradingMode, User
from binmarket_shared.trading.risk.manager import RiskManager

router = APIRouter(prefix="/api/settings", tags=["settings"])

LIVE_CONFIRMATION_PHRASE = "ACTIVAR LIVE"


class SettingsResponse(BaseModel):
    mode: TradingMode
    bot_enabled: bool
    bot_enabled_at: datetime | None
    bot_disabled_at: datetime | None
    bot_changed_by: str | None
    bot_change_reason: str | None
    max_risk_per_trade_pct: float
    max_total_exposure_pct: float
    max_position_size_pct: float
    max_daily_loss_pct: float
    max_weekly_loss_pct: float
    max_open_positions: int
    max_consecutive_losses: int
    min_expected_net_profit_pct: float
    taker_fee_pct: float
    maker_fee_pct: float
    default_slippage_pct: float
    paper_starting_balance_usdt: float
    emergency_stop_active: bool
    emergency_stop_reason: str | None
    wizard_completed: bool
    wizard_step: int
    auto_select_symbols_enabled: bool
    auto_select_max_symbols: int
    auto_select_min_volume_usdt: float
    stream_all_timeframes: bool
    orderbook_update_speed_ms: int

    class Config:
        from_attributes = True


class RiskSettingsUpdate(BaseModel):
    max_risk_per_trade_pct: float | None = None
    max_total_exposure_pct: float | None = None
    max_position_size_pct: float | None = None
    max_daily_loss_pct: float | None = None
    max_weekly_loss_pct: float | None = None
    max_open_positions: int | None = None
    max_consecutive_losses: int | None = None
    min_expected_net_profit_pct: float | None = None
    taker_fee_pct: float | None = None
    maker_fee_pct: float | None = None
    default_slippage_pct: float | None = None
    paper_starting_balance_usdt: float | None = None


class ModeChangeRequest(BaseModel):
    mode: TradingMode
    confirmation_phrase: str | None = None


class BotToggleRequest(BaseModel):
    enabled: bool
    reason: str | None = None


class WizardUpdate(BaseModel):
    step: int | None = None
    completed: bool | None = None


class EmergencyStopClearRequest(BaseModel):
    note: str | None = None


class AutoSelectUpdate(BaseModel):
    enabled: bool | None = None
    max_symbols: int | None = None
    min_volume_usdt: float | None = None


class NetworkSettingsUpdate(BaseModel):
    stream_all_timeframes: bool | None = None
    orderbook_update_speed_ms: int | None = None


def _settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> AppSettings:
    return _settings_row(db)


@router.put("/risk", response_model=SettingsResponse)
def update_risk_settings(
    payload: RiskSettingsUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> AppSettings:
    row = _settings_row(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.put("/mode", response_model=SettingsResponse)
def change_mode(
    payload: ModeChangeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AppSettings:
    row = _settings_row(db)

    if payload.mode == TradingMode.LIVE:
        if (payload.confirmation_phrase or "").strip().upper() != LIVE_CONFIRMATION_PHRASE:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Para activar LIVE hay que enviar confirmation_phrase = '{LIVE_CONFIRMATION_PHRASE}'",
            )
        if not row.wizard_completed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Completar el asistente de configuración antes de activar LIVE")

    previous_mode = row.mode
    row.mode = payload.mode
    # Any mode change forces the bot back OFF — switching modes with the bot
    # already running automatically would risk an unintended live order.
    row.bot_enabled = False
    row.bot_disabled_at = datetime.now(timezone.utc)
    row.bot_changed_by = user.username
    row.bot_change_reason = f"Modo cambiado de {previous_mode.value} a {payload.mode.value}"

    db.add(BotEvent(
        action=BotEventAction.MODE_CHANGED, performed_by=user.username,
        reason=row.bot_change_reason, context={"from": previous_mode.value, "to": payload.mode.value},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.post("/bot/toggle", response_model=SettingsResponse)
def toggle_bot(
    payload: BotToggleRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AppSettings:
    row = _settings_row(db)

    if payload.enabled and row.emergency_stop_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede encender el bot mientras Emergency Stop esté activo")

    now = datetime.now(timezone.utc)
    row.bot_enabled = payload.enabled
    row.bot_changed_by = user.username
    row.bot_change_reason = payload.reason
    if payload.enabled:
        row.bot_enabled_at = now
    else:
        row.bot_disabled_at = now

    db.add(BotEvent(
        action=BotEventAction.ENABLED if payload.enabled else BotEventAction.DISABLED,
        performed_by=user.username, reason=payload.reason, context={"mode": row.mode.value},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.put("/wizard", response_model=SettingsResponse)
def update_wizard(
    payload: WizardUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> AppSettings:
    row = _settings_row(db)
    if payload.step is not None:
        row.wizard_step = payload.step
    if payload.completed is not None:
        row.wizard_completed = payload.completed
    db.commit()
    db.refresh(row)
    return row


@router.post("/emergency-stop/clear", response_model=SettingsResponse)
def clear_emergency_stop(
    payload: EmergencyStopClearRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AppSettings:
    row = _settings_row(db)
    RiskManager(db, row).clear_emergency_stop(user.username, payload.note)
    db.commit()
    db.refresh(row)
    return row


@router.put("/auto-select", response_model=SettingsResponse)
def update_auto_select(
    payload: AutoSelectUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> AppSettings:
    row = _settings_row(db)
    if payload.enabled is not None:
        row.auto_select_symbols_enabled = payload.enabled
    if payload.max_symbols is not None:
        row.auto_select_max_symbols = max(1, payload.max_symbols)
    if payload.min_volume_usdt is not None:
        row.auto_select_min_volume_usdt = max(0.0, payload.min_volume_usdt)
    db.commit()
    db.refresh(row)
    return row


@router.put("/network", response_model=SettingsResponse)
def update_network_settings(
    payload: NetworkSettingsUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> AppSettings:
    row = _settings_row(db)
    if payload.stream_all_timeframes is not None:
        row.stream_all_timeframes = payload.stream_all_timeframes
    if payload.orderbook_update_speed_ms is not None:
        if payload.orderbook_update_speed_ms not in (100, 1000):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "orderbook_update_speed_ms debe ser 100 o 1000")
        row.orderbook_update_speed_ms = payload.orderbook_update_speed_ms
    db.commit()
    db.refresh(row)
    return row
