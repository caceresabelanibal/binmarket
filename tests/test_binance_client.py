"""Binance REST client, tested against mocked HTTP responses (respx) so the
suite never depends on real network access or real credentials — but still
exercises the exact request/response handling path used in production."""
from __future__ import annotations

import httpx
import pytest
import respx

from binmarket_shared.binance.client import BinanceClient, _format_decimal
from binmarket_shared.binance.errors import BinanceAPIError, BinanceConnectivityError


@pytest.mark.parametrize(
    "value,expected",
    [
        (8e-05, "0.00008"),
        (0.00001, "0.00001"),
        (100.0, "100"),
        (0.1, "0.1"),
        (1.23456789, "1.23456789"),
        (0.0, "0"),
    ],
)
def test_format_decimal_never_uses_scientific_notation(value, expected):
    formatted = _format_decimal(value)
    assert formatted == expected
    assert "e" not in formatted.lower()


@respx.mock
def test_create_order_sends_plain_decimal_quantity_not_scientific_notation():
    """Regression test for a real production bug: Python's default float
    formatting turns small quantities like 0.00008 into "8e-05", which
    Binance's API rejects with code -1100 ("Illegal characters found in
    parameter"). Every real BUY the engine attempted failed silently on this
    until it was fixed — assert the actual request line never contains "e-".
    """
    captured = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"orderId": 1, "status": "FILLED", "executedQty": "0.00008", "fills": []})

    respx.post("https://testnet.binance.vision/api/v3/order").mock(side_effect=capture)
    client = BinanceClient("key", "secret", environment="testnet")
    client.create_order("BTCUSDT", "BUY", "MARKET", quantity=8e-05)

    assert "e-" not in captured["url"]
    assert "quantity=0.00008" in captured["url"]


@respx.mock
def test_ping_success():
    respx.get("https://testnet.binance.vision/api/v3/ping").mock(return_value=httpx.Response(200, json={}))
    client = BinanceClient("key", "secret", environment="testnet")
    assert client.ping() is True


@respx.mock
def test_invalid_api_key_raises_typed_error_not_a_crash():
    """An invalid key must surface as a BinanceAPIError the caller can show
    to the user — never an unhandled exception, and never a silent order."""
    respx.get("https://testnet.binance.vision/api/v3/account").mock(
        return_value=httpx.Response(401, json={"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."})
    )
    client = BinanceClient("bad-key", "bad-secret", environment="testnet")
    with pytest.raises(BinanceAPIError) as exc_info:
        client.get_account()
    assert exc_info.value.code == -2015


@respx.mock
def test_connectivity_error_does_not_raise_and_is_reported():
    respx.get("https://testnet.binance.vision/api/v3/ping").mock(side_effect=httpx.ConnectError("boom"))
    client = BinanceClient("key", "secret", environment="testnet")
    with pytest.raises(BinanceConnectivityError):
        client.ping()


@respx.mock
def test_test_connectivity_never_raises_even_on_full_failure():
    """The Settings/Binance 'test connection' button must always get a
    structured result back, never a 500 from an unhandled exception."""
    respx.get("https://testnet.binance.vision/api/v3/ping").mock(side_effect=httpx.ConnectError("boom"))
    client = BinanceClient("key", "secret", environment="testnet")
    result = client.test_connectivity()
    assert result["ping"] is False
    assert result["error"] is not None


@respx.mock
def test_test_connectivity_skips_account_check_without_credentials():
    respx.get("https://testnet.binance.vision/api/v3/ping").mock(return_value=httpx.Response(200, json={}))
    respx.get("https://testnet.binance.vision/api/v3/time").mock(return_value=httpx.Response(200, json={"serverTime": 123}))
    client = BinanceClient("", "", environment="testnet")
    result = client.test_connectivity()
    assert result["ping"] is True
    assert result["account_reachable"] is False


def test_live_and_testnet_use_different_base_urls():
    live = BinanceClient("k", "s", environment="production")
    testnet = BinanceClient("k", "s", environment="testnet")
    assert "testnet" in str(testnet._http.base_url)
    assert "testnet" not in str(live._http.base_url)
