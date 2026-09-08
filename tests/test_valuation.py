"""compute_account_total_value is shared between the backend's "Capital
real" endpoint and the trading-engine's periodic history snapshot - tested
here once, against a duck-typed fake client (it only ever calls
`.get_account()` and `.get_ticker_24hr(symbol)`), rather than in both
call sites.
"""
from __future__ import annotations

from binmarket_shared.binance.errors import BinanceAPIError
from binmarket_shared.binance.valuation import compute_account_total_value


class FakeBinanceClient:
    def __init__(self, balances, tickers, account_error=None):
        self._balances = balances
        self._tickers = tickers
        self._account_error = account_error

    def get_account(self):
        if self._account_error:
            raise self._account_error
        return {"balances": self._balances}

    def get_ticker_24hr(self, symbol):
        if symbol not in self._tickers:
            raise BinanceAPIError(400, -1121, f"Invalid symbol {symbol}")
        return {"lastPrice": self._tickers[symbol]}


def _balance(asset, free, locked="0"):
    return {"asset": asset, "free": free, "locked": locked}


def test_values_holdings_and_converts_total_to_ars():
    client = FakeBinanceClient(
        balances=[_balance("USDT", "100"), _balance("BTC", "0.001")],
        tickers={"USDTARS": "1500", "BTCUSDT": "80000"},
    )
    result = compute_account_total_value(client)

    assert result["total_usdt"] == 180.0  # 100 + 0.001*80000
    assert result["total_ars"] == 180.0 * 1500
    assert result["usdt_ars_rate"] == 1500.0
    assert {b["asset"] for b in result["breakdown"]} == {"USDT", "BTC"}
    assert result["unvalued_assets"] == []


def test_ars_balance_converted_via_inverse_of_usdtars():
    # ARS only exists as a quote currency on Binance - never "ARSUSDT".
    client = FakeBinanceClient(
        balances=[_balance("ARS", "15000")],
        tickers={"USDTARS": "1500"},
    )
    result = compute_account_total_value(client)

    assert result["total_usdt"] == 10.0  # 15000 / 1500
    assert result["unvalued_assets"] == []


def test_zero_balances_are_excluded():
    client = FakeBinanceClient(
        balances=[_balance("USDT", "0", "0"), _balance("BTC", "0.001")],
        tickers={"USDTARS": "1500", "BTCUSDT": "80000"},
    )
    result = compute_account_total_value(client)

    assert {b["asset"] for b in result["breakdown"]} == {"BTC"}


def test_asset_with_no_direct_usdt_pair_falls_back_to_btc_pair():
    client = FakeBinanceClient(
        balances=[_balance("XYZ", "10")],
        tickers={"USDTARS": "1500", "XYZBTC": "0.00001", "BTCUSDT": "80000"},
    )
    result = compute_account_total_value(client)

    assert result["total_usdt"] == 10 * 0.00001 * 80000
    assert result["unvalued_assets"] == []


def test_asset_with_no_price_anywhere_is_reported_unvalued_not_dropped_silently():
    client = FakeBinanceClient(
        balances=[_balance("USDT", "100"), _balance("GHOST", "5")],
        tickers={"USDTARS": "1500"},
    )
    result = compute_account_total_value(client)

    assert result["total_usdt"] == 100.0
    assert result["unvalued_assets"] == [{"asset": "GHOST", "amount": 5.0}]


def test_missing_usdtars_rate_still_returns_total_usdt_with_an_error():
    client = FakeBinanceClient(balances=[_balance("USDT", "100")], tickers={})
    result = compute_account_total_value(client)

    assert "error" in result
    assert result["total_usdt"] == 100.0
    assert "total_ars" not in result


def test_account_fetch_failure_returns_just_an_error():
    client = FakeBinanceClient(
        balances=[], tickers={}, account_error=BinanceAPIError(401, -2015, "Invalid API-key"),
    )
    result = compute_account_total_value(client)

    assert "error" in result
    assert "total_usdt" not in result
