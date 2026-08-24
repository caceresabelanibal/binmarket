"""Trading cost model (section 13 of the spec).

Before any BUY signal is allowed to become an order, we compute:

    expected_net_profit = expected_gross_profit - fees - spread - slippage

and require it to clear a configurable minimum before the signal is anything
other than NO_TRADE. This is what stops the system from taking a trade that
looks good on the chart but is unprofitable once real trading costs are
accounted for.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostEstimate:
    gross_profit_pct: float
    round_trip_fee_pct: float
    spread_cost_pct: float
    slippage_cost_pct: float
    net_profit_pct: float
    risk_reward_ratio: float | None


def estimate_spread_pct(best_bid: float, best_ask: float) -> float:
    if best_bid <= 0 or best_ask <= 0:
        return 0.0
    mid = (best_bid + best_ask) / 2
    return ((best_ask - best_bid) / mid) * 100


def estimate_trade_economics(
    entry_price: float,
    take_profit_price: float,
    stop_loss_price: float | None,
    taker_fee_pct: float,
    spread_pct: float,
    slippage_pct: float,
) -> CostEstimate:
    gross_profit_pct = ((take_profit_price - entry_price) / entry_price) * 100
    round_trip_fee_pct = 2 * taker_fee_pct
    net_profit_pct = gross_profit_pct - round_trip_fee_pct - spread_pct - slippage_pct

    risk_reward_ratio = None
    if stop_loss_price and stop_loss_price < entry_price:
        risk = entry_price - stop_loss_price
        reward = take_profit_price - entry_price
        if risk > 0:
            risk_reward_ratio = reward / risk

    return CostEstimate(
        gross_profit_pct=gross_profit_pct,
        round_trip_fee_pct=round_trip_fee_pct,
        spread_cost_pct=spread_pct,
        slippage_cost_pct=slippage_pct,
        net_profit_pct=net_profit_pct,
        risk_reward_ratio=risk_reward_ratio,
    )


def passes_profitability_gate(cost_estimate: CostEstimate, min_expected_net_profit_pct: float) -> bool:
    return cost_estimate.net_profit_pct >= min_expected_net_profit_pct


def apply_slippage(price: float, side: str, slippage_pct: float) -> float:
    """Worse-case fill price used by the paper/backtest simulators.

    BUY fills slightly above the reference price, SELL fills slightly below —
    modelling the fact that market orders eat into the book.
    """
    factor = slippage_pct / 100
    if side.upper() == "BUY":
        return price * (1 + factor)
    return price * (1 - factor)
