"""Market regime classification (section 29 of the spec).

Classifies the current bar into a trend regime and a volatility regime using
only already-computed indicators (EMA20/50, ADX14, realized volatility). The
result is used to gate which strategies are eligible to trade right now —
e.g. Mean Reversion should not fire during a STRONG_UPTREND/DOWNTREND, and
nothing should fire during EXTREME_VOLATILITY.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

import pandas as pd

from binmarket_shared.quant.indicators import adx, ema, realized_volatility_pct


class TrendRegime(str, enum.Enum):
    STRONG_UPTREND = "STRONG_UPTREND"
    UPTREND = "UPTREND"
    SIDEWAYS = "SIDEWAYS"
    DOWNTREND = "DOWNTREND"
    STRONG_DOWNTREND = "STRONG_DOWNTREND"
    UNKNOWN = "UNKNOWN"


class VolatilityRegime(str, enum.Enum):
    LOW = "LOW_VOLATILITY"
    NORMAL = "NORMAL_VOLATILITY"
    HIGH = "HIGH_VOLATILITY"
    EXTREME = "EXTREME_VOLATILITY"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeReading:
    trend: TrendRegime
    volatility: VolatilityRegime
    adx_value: float
    volatility_pct: float

    @property
    def label(self) -> str:
        return f"{self.trend.value}/{self.volatility.value}"

    @property
    def is_tradeable(self) -> bool:
        return self.volatility != VolatilityRegime.EXTREME


def classify_regime(df: pd.DataFrame, lookback_for_vol_baseline: int = 100) -> RegimeReading:
    """`df` must have at least ~60 rows of OHLCV for a meaningful reading."""
    if len(df) < 55:
        return RegimeReading(TrendRegime.UNKNOWN, VolatilityRegime.UNKNOWN, 0.0, 0.0)

    close = df["close"]
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    adx14 = adx(df, 14)
    vol_pct = realized_volatility_pct(close, 20)

    last_ema20, last_ema50 = ema20.iloc[-1], ema50.iloc[-1]
    ema20_slope = ema20.iloc[-1] - ema20.iloc[-6] if len(ema20) > 6 else 0.0
    last_adx = float(adx14.iloc[-1]) if not pd.isna(adx14.iloc[-1]) else 0.0
    last_vol = float(vol_pct.iloc[-1]) if not pd.isna(vol_pct.iloc[-1]) else 0.0

    if pd.isna(last_ema20) or pd.isna(last_ema50):
        trend = TrendRegime.UNKNOWN
    elif last_ema20 > last_ema50:
        trend = TrendRegime.STRONG_UPTREND if (last_adx > 25 and ema20_slope > 0) else TrendRegime.UPTREND
    elif last_ema20 < last_ema50:
        trend = TrendRegime.STRONG_DOWNTREND if (last_adx > 25 and ema20_slope < 0) else TrendRegime.DOWNTREND
    else:
        trend = TrendRegime.SIDEWAYS

    if last_adx < 18 and abs(last_ema20 - last_ema50) / max(last_ema50, 1e-9) < 0.002:
        trend = TrendRegime.SIDEWAYS

    baseline = vol_pct.tail(lookback_for_vol_baseline).median()
    if pd.isna(baseline) or baseline <= 0:
        volatility = VolatilityRegime.UNKNOWN
    elif last_vol > baseline * 2.5:
        volatility = VolatilityRegime.EXTREME
    elif last_vol > baseline * 1.5:
        volatility = VolatilityRegime.HIGH
    elif last_vol < baseline * 0.5:
        volatility = VolatilityRegime.LOW
    else:
        volatility = VolatilityRegime.NORMAL

    return RegimeReading(trend=trend, volatility=volatility, adx_value=last_adx, volatility_pct=last_vol)
