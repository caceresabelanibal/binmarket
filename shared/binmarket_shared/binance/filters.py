"""Helpers to parse Binance `exchangeInfo` filters and enforce them locally.

The trading engine must never send an order Binance would reject for
violating LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL — position sizing rounds to
these constraints *before* an order is built (section 24 of the spec).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SymbolFilters:
    symbol: str
    tick_size: float
    step_size: float
    min_qty: float
    max_qty: float
    min_notional: float

    @classmethod
    def from_exchange_info_symbol(cls, symbol_info: dict) -> "SymbolFilters":
        tick_size = step_size = min_qty = max_qty = min_notional = 0.0
        for f in symbol_info.get("filters", []):
            ftype = f.get("filterType")
            if ftype == "PRICE_FILTER":
                tick_size = float(f["tickSize"])
            elif ftype == "LOT_SIZE":
                step_size = float(f["stepSize"])
                min_qty = float(f["minQty"])
                max_qty = float(f["maxQty"])
            elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(f.get("minNotional", f.get("minNotional", 0)) or 0)
        return cls(
            symbol=symbol_info["symbol"],
            tick_size=tick_size,
            step_size=step_size,
            min_qty=min_qty,
            max_qty=max_qty,
            min_notional=min_notional,
        )

    def round_price(self, price: float) -> float:
        return _round_to_step(price, self.tick_size)

    def round_quantity(self, quantity: float) -> float:
        return _round_to_step(quantity, self.step_size)

    def validate(self, price: float, quantity: float) -> tuple[bool, str | None]:
        if quantity < self.min_qty:
            return False, f"quantity {quantity} below min_qty {self.min_qty}"
        if self.max_qty and quantity > self.max_qty:
            return False, f"quantity {quantity} above max_qty {self.max_qty}"
        notional = price * quantity
        if self.min_notional and notional < self.min_notional:
            return False, f"notional {notional:.2f} below min_notional {self.min_notional}"
        return True, None


def _round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    precision = max(0, round(-math.log10(step)))
    rounded = math.floor(value / step) * step
    return round(rounded, precision)
