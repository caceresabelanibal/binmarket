"""Strategy plugin architecture (section 28 of the spec).

New strategies subclass `BaseStrategy` and register themselves in
`registry.py` — nothing else in the codebase needs to change to add one.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.quant.regime import RegimeReading
from binmarket_shared.quant.scoring import ScoreBreakdown


@dataclass
class OpenPositionView:
    """Read-only view of an existing open position, passed into strategies
    so they can decide whether to exit — strategies never write to the DB."""

    entry_price: float
    quantity: float
    stop_loss: float | None
    take_profit: float | None
    trailing_stop_pct: float | None
    highest_price_since_entry: float | None
    opened_at: Any


@dataclass
class StrategyContext:
    df: pd.DataFrame
    symbol: str
    timeframe: str
    regime: RegimeReading
    current_price: float
    best_bid: float | None
    best_ask: float | None
    available_capital: float
    current_total_exposure_value: float
    max_total_exposure_pct: float
    max_position_size_pct: float
    risk_per_trade_pct: float
    taker_fee_pct: float
    default_slippage_pct: float
    min_expected_net_profit_pct: float
    symbol_filters: SymbolFilters | None = None
    open_position: OpenPositionView | None = None


@dataclass
class StrategySignal:
    action: str  # "BUY" | "SELL" | "HOLD" | "NO_TRADE"
    scores: ScoreBreakdown
    reasons: list[str] = field(default_factory=list)
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    trailing_stop_pct: float | None = None
    expected_net_profit_pct: float | None = None
    risk_reward_ratio: float | None = None


class BaseStrategy(ABC):
    name: str = "base"
    version: str = "1.0.0"
    description: str = ""
    default_params: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None):
        self.params = {**self.default_params, **(params or {})}

    @property
    def min_bars_required(self) -> int:
        return 60

    @abstractmethod
    def is_regime_eligible(self, regime: RegimeReading) -> bool:
        """Whether this strategy should even be considered in this regime."""

    @abstractmethod
    def generate_signal(self, ctx: StrategyContext) -> StrategySignal:
        """Look only at `ctx.df` up to and including the last row — never at
        future bars — so this same method is safe for both live use and
        backtesting without look-ahead bias."""

    def should_exit_on_deterioration(self, ctx: StrategyContext) -> tuple[bool, str | None]:
        """Optional strategy-specific early-exit check (section 12: "cambia
        la tendencia", "aparece señal contraria", "se deteriora el score").
        Hard stop-loss/take-profit/trailing-stop exits are handled generically
        by the engine loop and don't need this.
        """
        return False, None
