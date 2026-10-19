"""Free, keyless daily OHLC - used only to score predictions against what
actually happened (never to place trades; that stays BinMarket's job).

Yahoo Finance's unofficial chart API is primary (richer - real index/ticker
symbols, intraday-capable, verified working with a browser UA). stooq.com
now sits behind a JS proof-of-work challenge (confirmed by hand - plain
`curl`/`httpx` gets a `noscript` challenge page back, not CSV, as of this
writing) so it's not usable headless anymore and isn't used here. FRED's
plain CSV export (no key required, confirmed working) is the fallback for
NASDAQCOM specifically if Yahoo ever rate-limits.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

_UA = "Mozilla/5.0 (compatible; MarketPulseBot/1.0)"


def fetch_yahoo_daily_closes(symbol: str, days_back: int = 30) -> list[tuple[date, float]]:
    """`symbol` as Yahoo spells it, e.g. "^IXIC", "^GSPC", "TSLA". Returns
    (date, close) pairs oldest-first. Empty list on any failure - callers
    must tolerate this source being temporarily unavailable."""
    range_param = "3mo" if days_back > 20 else "1mo"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        resp = httpx.get(
            url, params={"range": range_param, "interval": "1d"},
            headers={"User-Agent": _UA}, timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
    except Exception:
        return []

    timestamps = result.get("timestamp", [])
    closes = result["indicators"]["quote"][0].get("close", [])
    rows: list[tuple[date, float]] = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        rows.append((d, float(close)))
    return rows[-days_back:]


def fetch_fred_nasdaq_closes(days_back: int = 30) -> list[tuple[date, float]]:
    """Fallback: FRED's NASDAQCOM series (daily, going back to 1971), plain
    CSV, no API key. Used only if Yahoo is unavailable."""
    try:
        resp = httpx.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={"id": "NASDAQCOM"}, timeout=10.0,
        )
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()[1:]
    except Exception:
        return []

    rows: list[tuple[date, float]] = []
    for line in lines[-days_back:]:
        parts = line.split(",")
        if len(parts) != 2 or parts[1] == ".":
            continue
        try:
            rows.append((date.fromisoformat(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return rows


def fetch_daily_closes(symbol: str, days_back: int = 30) -> list[tuple[date, float]]:
    rows = fetch_yahoo_daily_closes(symbol, days_back)
    if rows:
        return rows
    if symbol in ("^IXIC",):
        return fetch_fred_nasdaq_closes(days_back)
    return []
