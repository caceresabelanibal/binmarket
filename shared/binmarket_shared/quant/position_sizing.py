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

        # Closing a position later nets out any commission paid in the base
        # asset and floors the result to this same LOT_SIZE step - so the
        # sell quantity is at best one step below what was bought here. And
        # the worst-case price at which this position is actually meant to
        # be sold isn't entry_price, it's stop_loss_price - that's the whole
        # point of a stop-loss. A real production bug checked only "one step
        # down, at entry_price", which barely passed at open (a razor-thin
        # margin) and then failed for real the moment the position had to
        # exit at its own (lower) stop-loss price, hitting -1013 NOTIONAL on
        # every retry with the loss uncapped and growing. Require the
        # position to still clear min_notional one step down, priced at its
        # OWN stop-loss - i.e. survivable in the scenario it's designed for.
        if symbol_filters.min_notional and symbol_filters.step_size:
            worst_case_price = min(entry_price, stop_loss_price)
            value_after_one_step_loss = (quantity - symbol_filters.step_size) * worst_case_price
            if value_after_one_step_loss < symbol_filters.min_notional:
                return PositionSizeResult(
                    0.0, 0.0, risk_amount, notes, False,
                    "quantity too close to min_notional - selling one lot step below this "
                    "(as commission-netting requires) at the stop-loss price would fall under "
                    "the exchange minimum, leaving no way to close this position if it loses",
                )

    if quantity <= 0:
        return PositionSizeResult(0.0, 0.0, risk_amount, notes, False, "rounded quantity is zero")

    return PositionSizeResult(
        quantity=quantity,
        position_value=position_value,
        risk_amount=risk_amount,
        notes=notes,
        is_tradeable=True,
    )
