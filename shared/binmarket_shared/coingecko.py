"""Best-effort commercial name + logo lookup for display purposes only
(e.g. "Bitcoin"/BTC next to the raw "BTCUSDT" trading pair in the UI).
Never used for trading decisions - CoinGecko is a free, unauthenticated,
best-effort source, and every caller must tolerate it being unavailable.
"""
from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("binmarket.coingecko")

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"

# CoinGecko's free tier rate-limits a burst of requests (observed a 429 on
# the 4th request in immediate succession) - a small gap between pages is
# cheap insurance against hitting it in the first place.
PAGE_DELAY_SECONDS = 1.5


def fetch_symbol_name_logo_map(
    pages: int = 4, per_page: int = 250, page_delay_seconds: float = PAGE_DELAY_SECONDS,
) -> dict[str, tuple[str, str]]:
    """Returns {SYMBOL: (display_name, logo_url)}, built from CoinGecko's
    market-cap-ranked coin list. Pages are requested in market-cap order, so
    when multiple coins share the same ticker (common - many small tokens
    reuse a symbol) the first (biggest) one seen wins and later duplicates
    are skipped, which is the sensible choice for a shared ticker.

    A failure partway through (e.g. a 429 on a later page) keeps whatever
    earlier pages already succeeded, rather than discarding all of it - a
    real incident hit rate limiting on page 4 of 4 and threw away pages 1-3,
    which had fetched fine. Returns an empty dict only if nothing at all
    could be fetched; never raises - this is a cosmetic enrichment step and
    must never block or fail the symbol sync it's called from.
    """
    result: dict[str, tuple[str, str]] = {}
    try:
        with httpx.Client(timeout=10.0) as client:
            for page in range(1, pages + 1):
                if page > 1 and page_delay_seconds:
                    time.sleep(page_delay_seconds)
                try:
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
                except Exception:
                    logger.warning(
                        "CoinGecko name/logo lookup failed on page %d/%d (keeping %d already fetched, non-fatal)",
                        page, pages, len(result), exc_info=True,
                    )
                    break
                if not coins:
                    break
                for coin in coins:
                    symbol = (coin.get("symbol") or "").upper()
                    name = coin.get("name")
                    image = coin.get("image")
                    if symbol and name and image and symbol not in result:
                        result[symbol] = (name, image)
    except Exception:
        logger.warning("CoinGecko name/logo lookup failed entirely (non-fatal, cosmetic only)", exc_info=True)
    return result
