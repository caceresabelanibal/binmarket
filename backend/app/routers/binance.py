from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.binance_factory import get_binance_client_for_mode
from app.core.deps import get_app_settings, get_current_user, get_db
from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.binance.errors import BinanceAPIError, BinanceConnectivityError
from binmarket_shared.config import settings as env_settings
from binmarket_shared.db.models import AppSettings, User

router = APIRouter(prefix="/api/binance", tags=["binance"])


class ConnectivityResponse(BaseModel):
    ping: bool
    server_time: int | None
    account_reachable: bool
    error: str | None
    environment: str
    masked_api_key: str


@router.post("/test-connectivity", response_model=ConnectivityResponse)
def test_connectivity(app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user)) -> dict:
    client = get_binance_client_for_mode(app_settings.mode)
    result = client.test_connectivity()
    client.close()
    return {**result, "environment": client.environment, "masked_api_key": env_settings.binance_masked_key}


@router.get("/account")
def get_account(app_settings: AppSettings = Depends(get_app_settings), _: User = Depends(get_current_user)) -> dict:
    client = get_binance_client_for_mode(app_settings.mode)
    try:
        account = client.get_account()
    except (BinanceAPIError, BinanceConnectivityError) as exc:
        return {"error": str(exc)}
    finally:
        client.close()

    balances = [b for b in account.get("balances", []) if float(b["free"]) > 0 or float(b["locked"]) > 0]
    can_withdraw = bool(account.get("canWithdraw", False))
    warnings = []
    if can_withdraw:
        warnings.append(
            "ADVERTENCIA: esta API Key tiene el permiso de retiros (withdrawals) habilitado. "
            "Nunca se debe usar una key con este permiso para trading automático; deshabilítalo en Binance."
        )
    return {
        "account_type": account.get("accountType"),
        "can_trade": account.get("canTrade"),
        "can_withdraw": can_withdraw,
        "balances": balances,
        "warnings": warnings,
    }


@router.get("/account/total-value")
def account_total_value(_: User = Depends(get_current_user)) -> dict:
    """Total value of every asset actually held in the Binance **spot**
    wallet, converted to ARS via Binance's own USDTARS market — independent
    of the app's current trading mode (PAPER/TESTNET/LIVE), because this is
    about the user's real account, not the simulator. Always queries
    production, since that's where a real account lives.

    Does not include Binance Earn/staking/savings balances — those live in a
    separate wallet the `/account` endpoint doesn't see either.
    """
    client = BinanceClient(env_settings.binance_api_key, env_settings.binance_api_secret, environment="production")
    try:
        try:
            account = client.get_account()
        except (BinanceAPIError, BinanceConnectivityError) as exc:
            return {"error": str(exc)}

        holdings = [
            (b["asset"], float(b["free"]) + float(b["locked"]))
            for b in account.get("balances", [])
            if float(b["free"]) + float(b["locked"]) > 0
        ]

        # ARS only exists on Binance as a QUOTE currency (USDTARS, BTCARS,
        # ...), never as a base pair like "ARSUSDT" — so a fiat ARS balance
        # has to be converted via the inverse of USDTARS, not looked up the
        # same way a crypto asset is. Fetch it once, up front, since both the
        # per-asset valuation below and the final USDT->ARS total need it.
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
    finally:
        client.close()


@router.get("/exchange-info")
def get_exchange_info(
    symbol: str | None = None,
    app_settings: AppSettings = Depends(get_app_settings),
    _: User = Depends(get_current_user),
) -> dict:
    client = get_binance_client_for_mode(app_settings.mode)
    try:
        return client.get_exchange_info(symbol)
    finally:
        client.close()
