"""Thin, explicit wrapper around the official Binance REST API.

Deliberately hand-rolled with httpx instead of a third-party SDK: we need full
control over which base URL is used for testnet vs. production (section 3 of
the spec), we need every signed call to be auditable, and we never want an
implicit dependency that could quietly add scopes we didn't ask for (e.g.
withdrawals). This is a synchronous client — async services call it through
`asyncio.to_thread` (see trading-engine/market-data), consistent with the
sync-everywhere DB decision documented in docs/architecture.md.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from binmarket_shared.binance.errors import BinanceAPIError, BinanceConnectivityError

Environment = Literal["testnet", "production"]

_REST_BASE_URLS: dict[Environment, str] = {
    "testnet": "https://testnet.binance.vision",
    "production": "https://api.binance.com",
}

_WS_BASE_URLS: dict[Environment, str] = {
    "testnet": "wss://stream.testnet.binance.vision:9443",
    "production": "wss://stream.binance.com:9443",
}


def _format_decimal(value: float) -> str:
    """Plain decimal string for any float going to Binance — never
    scientific notation, which their API rejects with code -1100."""
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text or "0"


def ws_base_url(environment: Environment) -> str:
    return _WS_BASE_URLS[environment]


class BinanceClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        environment: Environment = "testnet",
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self._api_secret = api_secret
        self.environment = environment
        self.timeout = timeout
        self._http = httpx.Client(
            base_url=_REST_BASE_URLS[environment],
            timeout=timeout,
            headers={"X-MBX-APIKEY": api_key} if api_key else {},
        )
        # Binance rejects any signed request whose timestamp is more than
        # ~1000ms ahead of its own server clock (code -1021), regardless of
        # recvWindow. Docker/WSL2 clocks drift after a host sleep/resume, so
        # rather than trust the container's clock we self-correct the first
        # time we actually see -1021 (see `_request`) and keep using that
        # offset for the rest of this client's life.
        self._server_time_offset_ms: int | None = None

    @property
    def ws_base_url(self) -> str:
        return _WS_BASE_URLS[self.environment]

    def close(self) -> None:
        self._http.close()

    # -- low level -----------------------------------------------------
    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode(params, doseq=True)
        signature = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return {**params, "signature": signature}

    def _synced_timestamp_ms(self) -> int:
        local_ms = int(time.time() * 1000)
        return local_ms + self._server_time_offset_ms if self._server_time_offset_ms else local_ms

    def sync_server_time(self) -> None:
        """Recomputes this client's clock offset against Binance's server
        time. Called automatically on a -1021 error; safe to call manually
        too (e.g. right after container startup)."""
        local_before = int(time.time() * 1000)
        server_ms = self.get_server_time()
        local_after = int(time.time() * 1000)
        self._server_time_offset_ms = server_ms - (local_before + local_after) // 2

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        _retried_after_resync: bool = False,
    ) -> Any:
        base_params = {k: v for k, v in (params or {}).items() if v is not None}
        # Python's default float->str uses scientific notation for small
        # values (e.g. 8e-05), which Binance's API rejects outright
        # (code -1100, "Illegal characters found in parameter") — every
        # quantity/price sent here MUST be plain decimal notation.
        base_params = {k: (_format_decimal(v) if isinstance(v, float) else v) for k, v in base_params.items()}

        request_params = dict(base_params)
        if signed:
            request_params["timestamp"] = self._synced_timestamp_ms()
            request_params["recvWindow"] = 5000
            request_params = self._sign(request_params)
        try:
            response = self._http.request(method, path, params=request_params)
        except httpx.RequestError as exc:
            raise BinanceConnectivityError(str(exc)) from exc

        if response.status_code >= 400:
            payload: dict[str, Any] = {}
            try:
                payload = response.json()
            except ValueError:
                pass
            code = payload.get("code")

            if signed and code == -1021 and not _retried_after_resync:
                self.sync_server_time()
                return self._request(method, path, base_params, signed=signed, _retried_after_resync=True)

            raise BinanceAPIError(
                status_code=response.status_code,
                code=code,
                message=payload.get("msg", response.text),
            )
        return response.json()

    # -- public / connectivity -----------------------------------------
    def ping(self) -> bool:
        self._request("GET", "/api/v3/ping")
        return True

    def get_server_time(self) -> int:
        return self._request("GET", "/api/v3/time")["serverTime"]

    def get_exchange_info(self, symbol: str | None = None) -> dict:
        params = {"symbol": symbol.upper()} if symbol else None
        return self._request("GET", "/api/v3/exchangeInfo", params)

    def get_ticker_24hr(self, symbol: str | None = None) -> Any:
        params = {"symbol": symbol.upper()} if symbol else None
        return self._request("GET", "/api/v3/ticker/24hr", params)

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        return self._request("GET", "/api/v3/depth", {"symbol": symbol.upper(), "limit": limit})

    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[list]:
        return self._request(
            "GET",
            "/api/v3/klines",
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "limit": limit,
            },
        )

    # -- account / trading (signed) --------------------------------------
    def get_account(self) -> dict:
        return self._request("GET", "/api/v3/account", signed=True)

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        params = {"symbol": symbol.upper()} if symbol else {}
        return self._request("GET", "/api/v3/openOrders", params, signed=True)

    def get_order(
        self, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None
    ) -> dict:
        return self._request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol.upper(), "orderId": order_id, "origClientOrderId": orig_client_order_id},
            signed=True,
        )

    def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float | None = None,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str | None = None,
        new_client_order_id: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
            "price": price,
            "stopPrice": stop_price,
            "timeInForce": time_in_force,
            "newClientOrderId": new_client_order_id,
            "newOrderRespType": "FULL",
        }
        return self._request("POST", "/api/v3/order", params, signed=True)

    def cancel_order(self, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None) -> dict:
        return self._request(
            "DELETE",
            "/api/v3/order",
            {"symbol": symbol.upper(), "orderId": order_id, "origClientOrderId": orig_client_order_id},
            signed=True,
        )

    def test_connectivity(self) -> dict[str, Any]:
        """Used by the Settings/Binance screen's "test connection" button."""
        result: dict[str, Any] = {"ping": False, "server_time": None, "account_reachable": False, "error": None}
        try:
            result["ping"] = self.ping()
            result["server_time"] = self.get_server_time()
            if self.api_key and self._api_secret:
                self.get_account()
                result["account_reachable"] = True
        except (BinanceAPIError, BinanceConnectivityError) as exc:
            result["error"] = str(exc)
        return result
