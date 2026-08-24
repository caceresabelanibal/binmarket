import pandas as pd
import pytest

from binmarket_shared.quant import indicators as ind


def _closes(values):
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="h"))


def test_sma_matches_manual_average():
    s = _closes([1, 2, 3, 4, 5])
    result = ind.sma(s, 3)
    assert result.iloc[-1] == pytest.approx((3 + 4 + 5) / 3)
    assert pd.isna(result.iloc[0])  # not enough data yet — no look-ahead fill


def test_ema_reacts_faster_than_sma_to_a_shock():
    values = [100] * 30 + [200] * 5
    s = _closes(values)
    sma20 = ind.sma(s, 20).iloc[-1]
    ema20 = ind.ema(s, 20).iloc[-1]
    assert ema20 > sma20  # EMA weighs the recent shock more heavily


def test_rsi_is_high_after_a_pure_uptrend():
    s = _closes([100 + i for i in range(30)])
    rsi = ind.rsi(s, 14)
    assert rsi.iloc[-1] > 90  # only gains, no losses -> RSI near 100


def test_rsi_is_low_after_a_pure_downtrend():
    s = _closes([200 - i for i in range(30)])
    rsi = ind.rsi(s, 14)
    assert rsi.iloc[-1] < 10


def test_bollinger_bands_widen_with_volatility():
    calm = _closes([100] * 25)
    volatile = _closes([100, 110, 90, 115, 85] * 5)
    calm_width = ind.bollinger_bands(calm).iloc[-1]["width_pct"]
    volatile_width = ind.bollinger_bands(volatile).iloc[-1]["width_pct"]
    assert volatile_width > calm_width


def test_atr_is_zero_for_flat_candles():
    df = pd.DataFrame(
        {"high": [100] * 20, "low": [100] * 20, "close": [100] * 20},
        index=pd.date_range("2024-01-01", periods=20, freq="h"),
    )
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(0.0)


def test_macd_histogram_positive_in_sustained_uptrend():
    s = _closes([100 + i * 0.5 for i in range(60)])
    macd_df = ind.macd(s)
    assert macd_df["histogram"].iloc[-1] > 0
