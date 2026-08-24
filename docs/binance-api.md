# Integración con Binance

## Antes que nada: permisos de la API Key

**La API Key usada por esta aplicación NUNCA debe tener habilitado "Enable Withdrawals" en Binance.** La UI (`Binance` page) advierte explícitamente si detecta que la key tiene ese permiso (`can_withdraw: true` en la respuesta de `/api/v3/account`), pero la única protección real es no habilitarlo nunca en el panel de Binance. Los permisos mínimos necesarios son: lectura de cuenta + trading spot.

## Testnet primero

1. Crear una cuenta en https://testnet.binance.vision/ y generar una API Key ahí (independiente de tu cuenta real).
2. Completar `BINANCE_API_KEY` / `BINANCE_API_SECRET` en `.env`, `BINANCE_ENVIRONMENT=testnet`.
3. Reiniciar el backend (`docker compose restart backend`) o simplemente esperar — las credenciales se leen del entorno del contenedor, no requieren reiniciar la base.
4. En `Binance → Probar conectividad` deberías ver `ping: OK` y `Cuenta accesible: SÍ`.

## Qué usa cada entorno

| Dato | Origen |
|---|---|
| Lista de símbolos + filtros (tick size, lot size, min notional) | Siempre Binance **producción**, público, sin key. |
| Velas históricas (backfill) | Binance producción, público, sin key. |
| Precio/order book en vivo (WebSocket) | Binance producción, público, sin key. |
| Cuenta / balances / órdenes reales | Testnet o producción según el modo activo (`TESTNET` → testnet, `LIVE` → producción). En modo `PAPER` se usa `BINANCE_ENVIRONMENT` solo para el botón "Probar conectividad". |

## Endpoints usados (`shared/binmarket_shared/binance/client.py`)

- `GET /api/v3/ping`, `/api/v3/time` — conectividad.
- `GET /api/v3/exchangeInfo` — símbolos y filtros (`PRICE_FILTER`, `LOT_SIZE`, `MIN_NOTIONAL`/`NOTIONAL`).
- `GET /api/v3/ticker/24hr`, `/api/v3/depth`, `/api/v3/klines` — datos de mercado.
- `GET /api/v3/account` (firmado) — balances y permisos.
- `POST /api/v3/order`, `GET /api/v3/order`, `DELETE /api/v3/order`, `GET /api/v3/openOrders` (firmados) — trading.

WebSocket combinado (`wss://.../stream?streams=...`): `<symbol>@ticker`, `<symbol>@depth5@100ms`, `<symbol>@kline_<tf>` por cada uno de los 8 timeframes soportados, para cada símbolo seleccionado.

## Manejo de errores y reconexión

- Toda llamada REST firmada que Binance rechace se traduce en `BinanceAPIError` (con el código/mensaje de Binance) — nunca en una excepción genérica no controlada, y nunca en una orden fabricada.
- El cliente WebSocket (`binmarket_shared/binance/ws.py`) reconecta con backoff exponencial (1s → 60s máx.) ante cualquier desconexión, y notifica el cambio de estado (`connected`/`disconnected`) para que el sistema sepa cuándo los datos de mercado podrían estar desactualizados.
- Un fallo de conectividad nunca genera una señal de trading "a ciegas": si no hay precio en caché, el `PaperExecutionProvider`/las estrategias simplemente no operan ese tick.
