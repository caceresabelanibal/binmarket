"""Best-effort commercial name + logo lookup for display purposes only
(e.g. "Bitcoin"/BTC next to the raw "BTCUSDT" trading pair in the UI).
Never used for trading decisions - CoinGecko is a free, unauthenticated,
best-effort source, and every caller must tolerate it being unavailable.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("binmarket.coingecko")

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"


def fetch_symbol_name_logo_map(pages: int = 4, per_page: int = 250) -> dict[str, tuple[str, str]]:
    """Returns {SYMBOL: (display_name, logo_url)}, built from CoinGecko's
    market-cap-ranked coin list. Pages are requested in market-cap order, so
    when multiple coins share the same ticker (common - many small tokens
    reuse a symbol) the first (biggest) one seen wins and later duplicates
    are skipped, which is the sensible choice for a shared ticker.

    Returns an empty dict on any failure (network, rate limit, unexpected
    shape) rather than raising - this is a cosmetic enrichment step and must
    never block or fail the symbol sync it's called from.
    """
    result: dict[str, tuple[str, str]] = {}
    try:
        with httpx.Client(timeout=10.0) as client:
            for page in range(1, pages + 1):
                resp = client.get(
                    COINGECKO_MARKETS_URL,
                    params={
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": per_page,
                        "page": page,
                        "sparkline": "false",
                    },
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                coins = resp.json()
                if not coins:
                    break
                for coin in coins:
                    symbol = (coin.get("symbol") or "").upper()
                    name = coin.get("name")
                    image = coin.get("image")
                    if symbol and name and image and symbol not in result:
                        result[symbol] = (name, image)
    except Exception:
        logger.warning("CoinGecko name/logo lookup failed (non-fatal, cosmetic only)", exc_info=True)
        return {}
    return result
