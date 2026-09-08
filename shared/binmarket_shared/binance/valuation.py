"""Real Binance spot-wallet valuation, shared between the backend's
"Capital real" endpoint and the trading-engine's periodic history snapshot -
both need the exact same ARS-converted total, computed the exact same way.
"""
from __future__ import annotations

from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.binance.errors import BinanceAPIError, BinanceConnectivityError


def compute_account_total_value(client: BinanceClient) -> dict:
    """Total value of every asset actually held in the Binance **spot**
    wallet, converted to ARS via Binance's own USDTARS market. Does not
    include Earn/staking/savings balances - those live in a separate wallet.
    """
    try:
        account = client.get_account()
    except (BinanceAPIError, BinanceConnectivityError) as exc:
        return {"error": str(exc)}

    holdings = [
        (b["asset"], float(b["free"]) + float(b["locked"]))
        for b in account.get("balances", [])
        if float(b["free"]) + float(b["locked"]) > 0
    ]

    # ARS only exists on Binance as a QUOTE currency (USDTARS, BTCARS, ...),
    # never as a base pair like "ARSUSDT" - so a fiat ARS balance has to be
    # converted via the inverse of USDTARS, not looked up the same way a
    # crypto asset is. Fetch it once, up front, since both the per-asset
    # valuation below and the final USDT->ARS total need it.
    usdt_ars_rate: float | None = None
    usdt_ars_error: str | None = None
    try:
        ars_ticker = client.get_ticker_24hr("USDTARS")
        usdt_ars_rate = float(ars_ticker["lastPrice"])
    except (BinanceAPIError, BinanceConnectivityError) as exc:
        usdt_ars_error = str(exc)

    price_cache: dict[str, float] = {}

    def usdt_price(asset: str) -> float | None:
        if asset == "USDT":
            return 1.0
        if asset == "ARS":
            return (1 / usdt_ars_rate) if usdt_ars_rate else None
        if asset in price_cache:
            return price_cache[asset]
        try:
            ticker = client.get_ticker_24hr(f"{asset}USDT")
            price_cache[asset] = float(ticker["lastPrice"])
            return price_cache[asset]
        except (BinanceAPIError, BinanceConnectivityError):
            pass
        try:
            via_btc = client.get_ticker_24hr(f"{asset}BTC")
            btc_price = usdt_price("BTC")
            if btc_price is not None:
                price_cache[asset] = float(via_btc["lastPrice"]) * btc_price
                return price_cache[asset]
        except (BinanceAPIError, BinanceConnectivityError):
            pass
        return None

    breakdown: list[dict] = []
    unvalued: list[dict] = []
    total_usdt = 0.0
    for asset, amount in holdings:
        price = usdt_price(asset)
        if price is None:
            unvalued.append({"asset": asset, "amount": amount})
            continue
        value_usdt = amount * price
        total_usdt += value_usdt
        breakdown.append({"asset": asset, "amount": amount, "price_usdt": price, "value_usdt": value_usdt})
    breakdown.sort(key=lambda x: x["value_usdt"], reverse=True)

    if usdt_ars_rate is None:
        return {
            "error": f"No se pudo obtener la cotización USDT/ARS: {usdt_ars_error}",
            "total_usdt": total_usdt,
            "breakdown": breakdown,
            "unvalued_assets": unvalued,
        }

    return {
        "total_usdt": total_usdt,
        "total_ars": total_usdt * usdt_ars_rate,
        "usdt_ars_rate": usdt_ars_rate,
        "breakdown": breakdown,
        "unvalued_assets": unvalued,
    }
