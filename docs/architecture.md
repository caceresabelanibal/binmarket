# Arquitectura

## Visión general

BinMarket es una plataforma de trading algorítmico de un solo usuario, pensada para correr por completo con Docker Compose. Se compone de seis servicios:

```
                        ┌──────────────┐
                        │   frontend   │  React + TS + Tailwind, servido por nginx
                        │  (nginx/vite)│  proxy /api y /ws → backend
                        └──────┬───────┘
                               │
                        ┌──────▼───────┐
        ┌───────────────┤   backend    ├───────────────┐
        │               │  (FastAPI)   │               │
        │               └──────┬───────┘               │
        │                      │                        │
┌───────▼──────┐       ┌───────▼────────┐       ┌───────▼───────┐
│  market-data  │       │   PostgreSQL   │       │     Redis      │
│ (WS + backfill)│◄─────┤  (única fuente │◄─────►│ (lock, cache,  │
└───────┬───────┘       │   de verdad)   │       │  pub/sub, cola)│
        │               └───────▲────────┘       └───────▲───────┘
        │                       │                        │
        │               ┌───────┴────────┐               │
        └──────────────►│ trading-engine ├───────────────┘
                         │ (loop asyncio) │
                         └────────────────┘
```

Todos los servicios Python (`backend`, `market-data`, `trading-engine`) comparten un único paquete de dominio, `shared/binmarket_shared`, instalado en modo editable dentro de cada imagen. Esto garantiza que existe **una sola implementación** de cada indicador, estrategia, modelo de costos, risk manager, execution provider y motor de backtesting — el backend la usa para backtests/preview de trading manual, y el trading-engine la usa para el loop en vivo. No hay duplicación de lógica de negocio entre servicios.

## Por qué no hay un séptimo servicio "scheduler"

Las tareas periódicas (snapshots de portfolio, reseteo implícito de contadores diarios de riesgo, heartbeats) viven dentro del loop asyncio de `trading-engine` en lugar de un servicio dedicado. Con un solo usuario y una cadencia de análisis de segundos/minutos, un scheduler separado sólo agregaría un punto de falla y complejidad operativa sin beneficio real.

## Por qué no hay comunicación HTTP interna entre servicios

`backend`, `market-data` y `trading-engine` nunca se llaman entre sí por HTTP. Comparten:

- **PostgreSQL** como única fuente de verdad (candles, señales, órdenes, posiciones, configuración).
- **Redis** para: lock distribuido (`ENGINE_LOCK_KEY`, evita doble ejecución del trading-engine), caché de último precio/order book (para no golpear la API de Binance en cada tick), cola de backfill (`BACKFILL_QUEUE_KEY`), pub/sub para el fan-out de WebSocket hacia el navegador, y heartbeats de salud.

Esto reduce el acoplamiento y evita que la caída de un servicio bloquee a otro. También es coherente con la sección 9 del pedido original: los indicadores/estrategias nunca están acoplados al código de ejecución de órdenes.

## Motor de decisión (extremo a extremo)

```
Candles (Postgres) → classify_regime() → estrategia elegible para el régimen
    → generate_signal() [scores + razones + entry/stop/target]
    → RuleBasedAdvisor.recommend() [contrato de IA, sin bypass posible]
    → costs.estimate_trade_economics() [gate de rentabilidad neta]
    → RiskManager.check_automatic_entry() [bot ON/OFF, exposición, pérdidas, emergency stop]
    → position_sizing.calculate_position_size() [redondeo a filtros de Binance]
    → OrderManager.open_position_from_signal() [idempotente]
    → ExecutionProvider (Paper | Testnet | Live)
    → Position/Order/Trade persistidos → Dashboard
```

Implementado en `shared/binmarket_shared/trading/engine_loop.py::process_symbol_tick`, reutilizado también por `docs/strategy.md`.

## Decisiones de simplificación explícitas (sección 44 del pedido)

Estas decisiones priorizan tener **lógica real y funcional** en el camino crítico por sobre una cobertura superficial de cada feature listada. Cada una queda documentada aquí para que una futura iteración sepa exactamente qué falta y por qué se dejó así:

1. **Stop-loss / take-profit / trailing-stop son gestionados por el engine loop, no como órdenes condicionales nativas de Binance.** Cada tick compara el precio actual contra los niveles guardados en `positions` y, si corresponde, cierra con una orden de mercado a través del mismo `ExecutionProvider`. Esto da comportamiento **idéntico** entre PAPER/TESTNET/LIVE (Paper no tiene forma de simular OCO orders de Binance) y evita la complejidad de gestionar order IDs condicionales duplicados. Una iteración futura podría añadir OCO nativas en LIVE como capa adicional de seguridad.
2. **Filtros de símbolo (tick size, lot size, min notional) se sincronizan siempre desde Binance producción**, incluso cuando el modo activo es TESTNET, porque el set de pares de testnet es mucho más limitado y sus filtros no siempre coinciden con producción. Si Binance testnet rechaza una orden por un filtro distinto, el `ExecutionProvider` lo captura como `BinanceAPIError` y lo registra como orden `REJECTED` — falla de forma segura, nunca de forma silenciosa.
3. **Walk-forward es una validación de ventanas rolantes con parámetros fijos**, no una re-optimización automática por ventana. Sirve para detectar que una estrategia se degrada fuera de la muestra de ajuste, pero la búsqueda de parámetros (sección 30) es una herramienta de grid-search simple y separada.
4. **La IA (sección 27) no incluye una llamada real a un LLM.** El pedido original solo exige que la arquitectura esté preparada para incorporarla; `RuleBasedAdvisor` implementa el contrato `AIAdvisor.recommend()` con lógica basada en reglas y sirve como implementación de referencia. Cualquier modelo real que se agregue después implementa la misma interfaz y sigue sin poder saltarse el Risk Manager — la garantía de seguridad no depende de qué produce la recomendación, sino de qué la valida.
5. **Portfolio**: se ofrece exposición por activo y una advertencia de concentración simple; no hay un optimizador de correlación/media-varianza completo.
6. **Order book**: se expone solo el top-of-book (mejor bid/ask), no profundidad completa, suficiente para estimar spread y slippage.

## Por qué SQLAlchemy síncrono en todos los servicios

Es una herramienta interna de un solo usuario, no un sistema de alto tráfico. Usar SQLAlchemy síncrono (psycopg2) en los tres servicios — incluidos los dos basados en asyncio (`market-data`, `trading-engine`), que envuelven cada llamada a la base con `asyncio.to_thread` — evita mantener dos stacks de drivers (`asyncpg` + `psycopg2` para Alembic) y simplifica Alembic, tests y el modelo mental completo del proyecto.

## Esquema de base de datos

Ver las migraciones en `database/versions/`. Tablas principales: `users`, `settings` (fila única, configuración operativa completa), `symbols`, `candles`, `signals`, `orders`, `trades`, `positions`, `strategies`, `strategy_runs`, `backtests` + `backtest_trades`, `portfolio_snapshots`, `balance_snapshots`, `bot_events`, `risk_events`, `system_logs`, `sync_jobs`.
