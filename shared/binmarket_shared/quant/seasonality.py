"""Hour-of-day seasonality (section: day-trading strategy's "weekly context"
phase, requested directly by the user).

Deliberately a transparent statistical read, not a black-box model: for a
given UTC hour, look back over the recent days of 1h candles and average
the % return of holding from that hour's open to its close. A positive
average means "this hour has recently tended to go up" for this specific
symbol - a real, explainable "mini modelo predictivo" whose reasoning shows
up in the Decision Log the same way every other score does, consistent with
the rest of this system never producing a signal nobody can explain.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class HourlyEdge:
    hour_utc: int
    avg_return_pct: float
    sample_count: int


def hourly_edge(df: pd.DataFrame, hour_utc: int, lookback_days: int = 7) -> HourlyEdge:
    """`df` must be 1h candles indexed by a tz-aware UTC DatetimeIndex
    (open_time). Looks at up to the last `lookback_days` days and averages
    the (close-open)/open % return of every candle whose hour matches
    `hour_utc`. `sample_count` is how many such candles were actually found
    - callers should treat a low count as low-confidence rather than
    rejecting it outright (a symbol only just backfilled has few, not zero,
    samples, and that's still better than guessing blind).
    """
    if df.empty or "open" not in df or "close" not in df:
        return HourlyEdge(hour_utc, 0.0, 0)

    window = df.tail(lookback_days * 24)
    hours = window.index.hour if hasattr(window.index, "hour") else pd.DatetimeIndex(window.index).hour
    matching = window[hours == hour_utc]
    if matching.empty:
        return HourlyEdge(hour_utc, 0.0, 0)

    returns = (matching["close"] - matching["open"]) / matching["open"] * 100
    return HourlyEdge(hour_utc, float(returns.mean()), len(matching))
