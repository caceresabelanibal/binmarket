import pandas as pd

from binmarket_shared.quant.regime import TrendRegime, VolatilityRegime, classify_regime


def _df(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="h")
    return pd.DataFrame(
        {"open": closes, "high": [c * 1.001 for c in closes], "low": [c * 0.999 for c in closes], "close": closes, "volume": 100.0},
        index=idx,
    )


def test_sustained_uptrend_is_classified_as_uptrend():
    closes = [100 + i * 0.8 for i in range(80)]
    reading = classify_regime(_df(closes))
    assert reading.trend in (TrendRegime.UPTREND, TrendRegime.STRONG_UPTREND)


def test_sustained_downtrend_is_classified_as_downtrend():
    closes = [200 - i * 0.8 for i in range(80)]
    reading = classify_regime(_df(closes))
    assert reading.trend in (TrendRegime.DOWNTREND, TrendRegime.STRONG_DOWNTREND)


def test_flat_price_is_classified_sideways():
    closes = [100.0] * 80
    reading = classify_regime(_df(closes))
    assert reading.trend == TrendRegime.SIDEWAYS


def test_insufficient_data_is_unknown_not_a_guess():
    reading = classify_regime(_df([100.0] * 10))
    assert reading.trend == TrendRegime.UNKNOWN
    assert reading.volatility == VolatilityRegime.UNKNOWN
