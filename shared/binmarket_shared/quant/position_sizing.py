"""Position sizing (section 11 of the spec).

Quantity is never arbitrary: it is derived from how much capital we are
willing to risk on this specific trade (distance to stop-loss), then capped
by per-position and total-exposure limits, then rounded down to what the
exchange's LOT_SIZE/MIN_NOTIONAL filters actually allow.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from binmarket_shared.binance.filters import SymbolFilters


@dataclass
class PositionSizeResult:
    quantity: float
    position_value: float
    risk_amount: float
    notes: list[str] = field(default_factory=list)
    is_tradeable: bool = True
    rejection_reason: str | None = None


def calculate_position_size(
    available_capital: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_loss_price: float,
    current_total_exposure_value: float,
    max_total_exposure_pct: float,
    max_position_size_pct: float,
    symbol_filters: SymbolFilters | None = None,
) -> PositionSizeResult:
    notes: list[str] = []

    if entry_price <= 0 or stop_loss_price <= 0 or stop_loss_price >= entry_price:
        return PositionSizeResult(0.0, 0.0, 0.0, notes, False, "invalid entry/stop-loss prices")

    stop_distance_pct = (entry_price - stop_loss_price) / entry_price
    risk_amount = available_capital * (risk_per_trade_pct / 100)
    raw_quantity = risk_amount / (entry_price * stop_distance_pct)
    position_value = raw_quantity * entry_price

    max_position_value = available_capital * (max_position_size_pct / 100)
    if position_value > max_position_value:
        notes.append(f"capped by max_position_size_pct ({max_position_size_pct}% of capital)")
        position_value = max_position_value

    remaining_exposure_budget = max(
        (available_capital * (max_total_exposure_pct / 100)) - current_total_exposure_value, 0.0
    )
    if position_value > remaining_exposure_budget:
        notes.append(f"capped by remaining exposure budget (max_total_exposure_pct={max_total_exposure_pct}%)")
        position_value = remaining_exposure_budget

    if position_value <= 0:
        return PositionSizeResult(0.0, 0.0, risk_amount, notes, False, "no exposure budget remaining")

    quantity = position_value / entry_price

    if symbol_filters:
        quantity = symbol_filters.round_quantity(quantity)
        position_value = quantity * entry_price
        ok, reason = symbol_filters.validate(entry_price, quantity)
        if not ok:
            return PositionSizeResult(0.0, 0.0, risk_amount, notes, False, reason)

    if quantity <= 0:
        return PositionSizeResult(0.0, 0.0, risk_amount, notes, False, "rounded quantity is zero")

    return PositionSizeResult(
        quantity=quantity,
        position_value=position_value,
        risk_amount=risk_amount,
        notes=notes,
        is_tradeable=True,
    )
