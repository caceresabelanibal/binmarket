"""fetch_symbol_name_logo_map is a cosmetic, best-effort lookup - the whole
point is it must never blow up the symbol sync it's called from, whatever
CoinGecko does (down, rate-limited, empty, malformed).
"""
from __future__ import annotations

import httpx
import respx

from binmarket_shared.coingecko import COINGECKO_MARKETS_URL, fetch_symbol_name_logo_map


def _coin(symbol, name, image):
    return {"symbol": symbol, "name": name, "image": image}


@respx.mock
def test_builds_symbol_to_name_logo_map_from_first_page():
    respx.get(COINGECKO_MARKETS_URL).mock(
        side_effect=[
            httpx.Response(200, json=[_coin("btc", "Bitcoin", "https://x/btc.png"), _coin("eth", "Ethereum", "https://x/eth.png")]),
            httpx.Response(200, json=[]),  # page 2 empty -> stop early
        ]
    )
    result = fetch_symbol_name_logo_map(pages=4)

    assert result["BTC"] == ("Bitcoin", "https://x/btc.png")
    assert result["ETH"] == ("Ethereum", "https://x/eth.png")


@respx.mock
def test_higher_market_cap_coin_wins_a_shared_ticker():
    # CoinGecko returns coins in market-cap-descending order - the first
    # (biggest) coin seen for a given ticker should win over a smaller one
    # that reuses the same symbol later in the list.
    respx.get(COINGECKO_MARKETS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[_coin("luna", "Terra Luna Classic", "https://x/luna-big.png"), _coin("luna", "Some Obscure Luna Clone", "https://x/luna-small.png")],
        )
    )
    result = fetch_symbol_name_logo_map(pages=1)

    assert result["LUNA"] == ("Terra Luna Classic", "https://x/luna-big.png")


@respx.mock
def test_network_failure_returns_empty_dict_not_an_exception():
    respx.get(COINGECKO_MARKETS_URL).mock(side_effect=httpx.ConnectError("boom"))

    result = fetch_symbol_name_logo_map()

    assert result == {}


@respx.mock
def test_rate_limit_response_returns_empty_dict_not_an_exception():
    respx.get(COINGECKO_MARKETS_URL).mock(return_value=httpx.Response(429, json={"error": "rate limited"}))

    result = fetch_symbol_name_logo_map()

    assert result == {}


@respx.mock
def test_coin_missing_an_image_is_skipped_not_stored_with_a_blank_logo():
    respx.get(COINGECKO_MARKETS_URL).mock(
        return_value=httpx.Response(200, json=[{"symbol": "xyz", "name": "Xyz Coin", "image": None}])
    )
    result = fetch_symbol_name_logo_map(pages=1)

    assert result == {}
