"""AI recommendation contract (section 27 of the spec).

`AIAdvisor.recommend()` returns a structured `AIRecommendation` — never an
order, never a direct action. The pipeline is always:

    Strategy -> AIAdvisor -> RiskManager -> position sizing -> OrderManager

`RuleBasedAdvisor` is the V1 implementation and does not call an external
LLM (none was concretely specified, and fabricating an integration nobody
asked for would be worse than being explicit about the gap). It exists to
prove the contract end-to-end: a future model-backed advisor is a drop-in
replacement for this class and — like this one — is structurally incapable
of bypassing the Risk Manager, because nothing downstream of `recommend()`
ever executes a trade without going through it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from binmarket_shared.trading.strategies.base import StrategyContext, StrategySignal


@dataclass
class AIRecommendation:
    action: str
    confidence: float
    symbol: str
    position_size_pct: float | None
    stop_loss_pct: float | None
    take_profit_pct: float | None
    reasoning: list[str] = field(default_factory=list)


class AIAdvisor(ABC):
    @abstractmethod
    def recommend(self, ctx: StrategyContext, strategy_signal: StrategySignal) -> AIRecommendation:
        ...


class RuleBasedAdvisor(AIAdvisor):
    def recommend(self, ctx: StrategyContext, strategy_signal: StrategySignal) -> AIRecommendation:
        confidence = round(strategy_signal.scores.opportunity_score / 100, 3)

        stop_loss_pct = None
        take_profit_pct = None
        if strategy_signal.entry_price:
            if strategy_signal.stop_loss:
                stop_loss_pct = abs(strategy_signal.entry_price - strategy_signal.stop_loss) / strategy_signal.entry_price
            if strategy_signal.take_profit:
                take_profit_pct = abs(strategy_signal.take_profit - strategy_signal.entry_price) / strategy_signal.entry_price

        return AIRecommendation(
            action=strategy_signal.action,
            confidence=confidence,
            symbol=ctx.symbol,
            position_size_pct=None,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            reasoning=strategy_signal.reasons,
        )
