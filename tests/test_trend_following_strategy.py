from __future__ import annotations

import pytest

from binmarket_shared.quant.regime import RegimeReading, TrendRegime, VolatilityRegime
from binmarket_shared.trading.strategies.trend_following import TrendFollowingStrategy


@pytest.mark.parametrize(
    "trend,volatility,expected",
    [
        # Real backtest over 540 days of real ETHUSDT/BTCUSDT 1h data showed
        # plain UPTREND entries (ADX<=25 or a flat EMA20 slope) dragging down
        # overall expectancy - only STRONG_UPTREND is eligible now, see the
        # comment on is_regime_eligible for the numbers.
        (TrendRegime.STRONG_UPTREND, VolatilityRegime.NORMAL, True),
        (TrendRegime.STRONG_UPTREND, VolatilityRegime.HIGH, True),
        (TrendRegime.STRONG_UPTREND, VolatilityRegime.LOW, True),
        (TrendRegime.STRONG_UPTREND, VolatilityRegime.EXTREME, False),
        (TrendRegime.UPTREND, VolatilityRegime.NORMAL, False),
        (TrendRegime.SIDEWAYS, VolatilityRegime.NORMAL, False),
        (TrendRegime.DOWNTREND, VolatilityRegime.NORMAL, False),
        (TrendRegime.STRONG_DOWNTREND, VolatilityRegime.NORMAL, False),
    ],
)
def test_only_strong_uptrend_with_non_extreme_volatility_is_eligible(trend, volatility, expected):
    strategy = TrendFollowingStrategy()
    regime = RegimeReading(trend=trend, volatility=volatility, adx_value=30.0, volatility_pct=1.0)
    assert strategy.is_regime_eligible(regime) is expected
