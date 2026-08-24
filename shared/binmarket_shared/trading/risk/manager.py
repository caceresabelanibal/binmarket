"""Risk Manager (section 14 of the spec) — the single gatekeeper that every
BUY, whether automatic or manual, must pass through. Nothing else in the
codebase is allowed to open a position while this says no.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from binmarket_shared.db.models import AppSettings, BotEvent, BotEventAction, Position, PositionStatus, RiskEvent, RiskSeverity, TradingMode
from binmarket_shared.notifications import AlertEvent, AlertLevel, notify


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str | None = None


def _today_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class RiskManager:
    def __init__(self, db: Session, settings_row: AppSettings):
        self.db = db
        self.settings = settings_row

    # -- state readers ---------------------------------------------------
    def open_positions(self, mode: TradingMode) -> list[Position]:
        stmt = select(Position).where(Position.status == PositionStatus.OPEN, Position.mode == mode)
        return list(self.db.execute(stmt).scalars().all())

    def open_positions_count(self, mode: TradingMode) -> int:
        return len(self.open_positions(mode))

    def total_exposure_value(self, mode: TradingMode) -> float:
        return sum(p.entry_price * p.quantity for p in self.open_positions(mode))

    def _closed_positions_since(self, mode: TradingMode, since: datetime) -> list[Position]:
        stmt = select(Position).where(
            Position.status == PositionStatus.CLOSED, Position.mode == mode, Position.closed_at >= since
        )
        return list(self.db.execute(stmt).scalars().all())

    def realized_pnl_since(self, mode: TradingMode, since: datetime) -> float:
        return sum(p.realized_pnl for p in self._closed_positions_since(mode, since))

    def daily_realized_pnl(self, mode: TradingMode) -> float:
        return self.realized_pnl_since(mode, _today_start(datetime.now(timezone.utc)))

    def weekly_realized_pnl(self, mode: TradingMode) -> float:
        return self.realized_pnl_since(mode, datetime.now(timezone.utc) - timedelta(days=7))

    def consecutive_losing_trades(self, mode: TradingMode) -> int:
        stmt = (
            select(Position)
            .where(Position.status == PositionStatus.CLOSED, Position.mode == mode)
            .order_by(Position.closed_at.desc())
            .limit(50)
        )
        count = 0
        for p in self.db.execute(stmt).scalars().all():
            if p.realized_pnl < 0:
                count += 1
            else:
                break
        return count

    # -- gates -------------------------------------------------------------
    def bot_can_trade_automatically(self) -> RiskCheckResult:
        if self.settings.emergency_stop_active:
            return RiskCheckResult(False, f"Emergency Stop activo: {self.settings.emergency_stop_reason or 'sin motivo registrado'}")
        if not self.settings.bot_enabled:
            return RiskCheckResult(False, "El trading automático está apagado (OFF)")
        return RiskCheckResult(True)

    def check_common_limits(
        self, position_value: float, available_capital: float, mode: TradingMode
    ) -> RiskCheckResult:
        s = self.settings

        if s.emergency_stop_active:
            return RiskCheckResult(False, f"Emergency Stop activo: {s.emergency_stop_reason or 'sin motivo registrado'}")

        if self.open_positions_count(mode) >= s.max_open_positions:
            return RiskCheckResult(False, f"Se alcanzó el máximo de posiciones abiertas ({s.max_open_positions})")

        if available_capital <= 0:
            return RiskCheckResult(False, "Sin capital disponible")

        if position_value > available_capital * (s.max_position_size_pct / 100):
            return RiskCheckResult(False, f"El tamaño de posición excede max_position_size_pct ({s.max_position_size_pct}%)")

        exposure = self.total_exposure_value(mode)
        if (exposure + position_value) > available_capital * (s.max_total_exposure_pct / 100):
            return RiskCheckResult(False, f"Excedería la exposición total máxima ({s.max_total_exposure_pct}%)")

        daily_pnl_pct = self.daily_realized_pnl(mode) / available_capital * 100
        if daily_pnl_pct <= -s.max_daily_loss_pct:
            return RiskCheckResult(False, f"Pérdida diaria ({daily_pnl_pct:.2f}%) alcanzó el límite ({s.max_daily_loss_pct}%)")

        weekly_pnl_pct = self.weekly_realized_pnl(mode) / available_capital * 100
        if weekly_pnl_pct <= -s.max_weekly_loss_pct:
            return RiskCheckResult(False, f"Pérdida semanal ({weekly_pnl_pct:.2f}%) alcanzó el límite ({s.max_weekly_loss_pct}%)")

        if self.consecutive_losing_trades(mode) >= s.max_consecutive_losses:
            return RiskCheckResult(False, f"Se alcanzaron {s.max_consecutive_losses} operaciones perdedoras consecutivas")

        return RiskCheckResult(True)

    def check_automatic_entry(
        self, position_value: float, available_capital: float, mode: TradingMode
    ) -> RiskCheckResult:
        bot_check = self.bot_can_trade_automatically()
        if not bot_check.allowed:
            return bot_check
        return self.check_common_limits(position_value, available_capital, mode)

    def check_manual_entry(
        self, position_value: float, available_capital: float, mode: TradingMode
    ) -> RiskCheckResult:
        """Manual trades bypass the bot ON/OFF switch (it's an explicit human
        action) but never bypass hard risk/exposure/emergency-stop limits."""
        return self.check_common_limits(position_value, available_capital, mode)

    # -- emergency stop -----------------------------------------------------
    def run_periodic_safety_checks(self, mode: TradingMode, available_capital: float) -> None:
        if self.settings.emergency_stop_active or available_capital <= 0:
            return

        daily_pnl_pct = self.daily_realized_pnl(mode) / available_capital * 100
        if daily_pnl_pct <= -self.settings.max_daily_loss_pct:
            self.trigger_emergency_stop(
                f"Pérdida diaria realizada de {daily_pnl_pct:.2f}% superó el límite configurado "
                f"({self.settings.max_daily_loss_pct}%)"
            )
            return

        losses = self.consecutive_losing_trades(mode)
        if losses >= self.settings.max_consecutive_losses:
            self.trigger_emergency_stop(f"{losses} operaciones perdedoras consecutivas alcanzaron el límite configurado")

    def trigger_emergency_stop(self, reason: str) -> None:
        self.settings.emergency_stop_active = True
        self.settings.bot_enabled = False
        self.settings.bot_disabled_at = datetime.now(timezone.utc)
        self.settings.bot_changed_by = "risk_manager"
        self.settings.bot_change_reason = reason
        self.settings.emergency_stop_reason = reason

        self.db.add(RiskEvent(event_type="EMERGENCY_STOP", severity=RiskSeverity.CRITICAL, details={"reason": reason}))
        self.db.add(BotEvent(action=BotEventAction.EMERGENCY_STOP, performed_by="risk_manager", reason=reason))
        self.db.flush()

        notify(AlertEvent(
            title="EMERGENCY STOP activado",
            message=reason,
            level=AlertLevel.CRITICAL,
            category="risk",
        ))

    def clear_emergency_stop(self, cleared_by: str, note: str | None = None) -> None:
        self.settings.emergency_stop_active = False
        self.settings.emergency_stop_reason = None
        self.db.add(RiskEvent(
            event_type="EMERGENCY_STOP_CLEARED",
            severity=RiskSeverity.INFO,
            details={"cleared_by": cleared_by, "note": note},
        ))
