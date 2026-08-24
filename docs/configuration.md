# Configuración

## Variables de entorno (`.env`)

Ver `.env.example` para la lista completa comentada. Las más relevantes:

| Variable | Descripción |
|---|---|
| `SECRET_KEY` | Firma los JWT de sesión. Cambiar siempre en producción. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Único usuario de la aplicación. Se crea/actualiza en cada arranque del backend. |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Vacías por defecto. Ver `docs/binance-api.md`. |
| `BINANCE_ENVIRONMENT` | `testnet` o `production`. Usado por TESTNET/LIVE al operar y por el chequeo de conectividad en modo PAPER. |
| `POSTGRES_*` | Conexión a la base. |
| `REDIS_URL` | Conexión a Redis. |
| `ENGINE_LOOP_INTERVAL_SECONDS` | Cada cuánto el trading-engine evalúa los símbolos seleccionados. |
| `TELEGRAM_*`, `DISCORD_WEBHOOK_URL`, `SMTP_*` | Canales de alertas opcionales — si se dejan vacíos, ese canal simplemente no se usa. |

## Configuración operativa (vía UI, tabla `settings`)

No requiere reiniciar ningún servicio — todo se lee de la base de datos en cada tick/request:

- **Modo**: PAPER / TESTNET / LIVE (`Settings → Modo de operación`).
- **Riesgo**: `max_risk_per_trade_pct`, `max_total_exposure_pct`, `max_position_size_pct`, `max_daily_loss_pct`, `max_weekly_loss_pct`, `max_open_positions`, `max_consecutive_losses` (`Settings → Riesgo y costos`).
- **Costos**: `taker_fee_pct`, `maker_fee_pct`, `default_slippage_pct`, `min_expected_net_profit_pct` — este último es el umbral mínimo de ganancia neta esperada (después de comisiones/spread/slippage) para que una señal BUY se convierta en orden.
- **Capital inicial de Paper Trading**: `paper_starting_balance_usdt`.
- **Bot ON/OFF**: desde la barra superior, con motivo opcional y quedando registrado en `bot_events`.

## Selección de criptomonedas

`Market → Sincronizar pares desde Binance` puebla la tabla `symbols` con todos los pares en estado `TRADING` de Binance (siempre desde producción, ver `docs/architecture.md`). Marcar el checkbox de un par lo agrega a la lista que el trading-engine efectivamente analiza; el favorito (★) es solo para ordenar/filtrar en la UI.

## Parámetros de estrategia

Cada estrategia (`trend_following`, `mean_reversion`, `breakout`) tiene sus parámetros en la tabla `strategies` (JSON), editables desde `Strategies`. Ver `docs/strategy.md` para el significado de cada parámetro.
