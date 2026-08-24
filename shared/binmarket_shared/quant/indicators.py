"""Technical indicators. Every function takes a pandas DataFrame with at
least the columns it needs (open, high, low, close, volume) indexed by time
ascending, and returns a pandas Series aligned to the same index.

All calculations only ever look at data up to and including the current row
(rolling/expanding windows ending at `t`), which is what keeps backtests free
of look-ahead bias when these same functions are reused bar-by-bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    # avg_loss == 0 means no losing bars at all in the window -> RSI is 100
    # (maximally overbought), not the NaN that avg_gain/0 produces.
    result = result.where(avg_loss != 0, 100.0)
    # ...unless avg_gain is also 0 (a perfectly flat price, no moves either
    # way) -> neutral 50, not "maximally overbought".
    result = result.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    # Still-NaN rows are the genuine warmup period (fewer than `period` bars
    # of history yet) -> neutral 50 is the right "don't know yet" default.
    return result.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width_pct = ((upper - lower) / mid.replace(0, np.nan)) * 100
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower, "width_pct": width_pct})


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_period_atr = atr(df, period).replace(0, np.nan)

    plus_dm_smoothed = pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    minus_dm_smoothed = pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    plus_di = 100 * (plus_dm_smoothed / tr_period_atr)
    minus_di = 100 * (minus_dm_smoothed / tr_period_atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().fillna(0.0)


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session-less rolling VWAP over the full available window (cumulative)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_pv = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum().replace(0, np.nan)
    return cumulative_pv / cumulative_vol


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return sma(df["volume"], period)


def realized_volatility_pct(series: pd.Series, period: int = 20) -> pd.Series:
    """Annualization-free realized volatility, expressed as a % of price."""
    returns = series.pct_change()
    return returns.rolling(window=period, min_periods=period).std() * 100
