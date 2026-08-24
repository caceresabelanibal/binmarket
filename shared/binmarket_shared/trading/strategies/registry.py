from __future__ import annotations

from .base import BaseStrategy
from .breakout import BreakoutStrategy
from .mean_reversion import MeanReversionStrategy
from .trend_following import TrendFollowingStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    TrendFollowingStrategy.name: TrendFollowingStrategy,
    MeanReversionStrategy.name: MeanReversionStrategy,
    BreakoutStrategy.name: BreakoutStrategy,
}


def get_strategy(name: str, params: dict | None = None) -> BaseStrategy:
    try:
        cls = STRATEGY_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGY_REGISTRY)}") from exc
    return cls(params)


def eligible_strategies(regime, priority: list[str] | None = None) -> list[BaseStrategy]:
    """Instantiates strategies (default params) in priority order, filtered
    to those eligible for the given market regime. `priority` lets Settings
    override which strategy "wins" when more than one would be eligible.
    """
    names = priority or list(STRATEGY_REGISTRY.keys())
    strategies = [get_strategy(n) for n in names if n in STRATEGY_REGISTRY]
    return [s for s in strategies if s.is_regime_eligible(regime)]
