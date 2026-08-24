# Seguridad

## Credenciales

- Las API Keys de Binance viven solo en variables de entorno (`.env`, nunca committeado — ver `.gitignore`). Ningún código las hardcodea.
- El API Secret nunca se devuelve completo por la API ni se loguea; `binmarket_shared.config.Settings.binance_masked_key` expone solo los últimos 4 caracteres.
- La UI (`Binance` page) muestra explícitamente una advertencia si la key configurada tiene el permiso de retiros habilitado.

## Autenticación

- Un único usuario, sembrado desde `ADMIN_USERNAME`/`ADMIN_PASSWORD` en cada arranque del backend (`backend/app/seed.py`) — la contraseña se re-hashea en cada arranque, así que cambiarla en `.env` y reiniciar el backend es suficiente para rotarla.
- Contraseña con bcrypt (`passlib`).
- Sesión vía JWT en cookie `httponly`, `samesite=lax`, `secure` cuando `APP_ENV=production`.
- Rate limiting en `/api/auth/login` (`slowapi`, 10/minuto) para dificultar fuerza bruta.

## Modos de operación y confirmaciones

- El indicador de modo (PAPER azul / TESTNET ámbar / LIVE rojo parpadeante) es siempre visible en la barra superior — nunca hay una vista donde el modo activo sea ambiguo.
- Cambiar a modo LIVE exige: haber completado el asistente de configuración (`wizard_completed`) y escribir literalmente la frase `ACTIVAR LIVE` (`backend/app/routers/settings.py`).
- Cualquier cambio de modo apaga el bot automáticamente — nunca se pasa de un modo a otro con el trading automático ya corriendo.
- Encender/apagar el bot registra quién, cuándo y por qué (`bot_events`).

## Riesgo como límite duro, no como sugerencia

Ver `docs/strategy.md` y `shared/binmarket_shared/trading/risk/manager.py`. El Risk Manager es el único punto por el que pasa cualquier apertura de posición (automática o manual) y no puede ser evitado por una estrategia, por la IA, ni por el usuario en modo manual — el Emergency Stop bloquea inclusive las operaciones manuales.

## Idempotencia

Cada orden tiene un `client_order_id` **determinístico** (hash de la señal/posición + modo), no un UUID aleatorio. Reintentar la misma señal (por un reinicio, una duplicación del proceso, etc.) nunca produce una segunda orden real — la restricción `UNIQUE` de la base de datos es la última línea de defensa (`shared/binmarket_shared/trading/orders/manager.py`).

## Lock distribuido

`trading-engine` adquiere un lock en Redis (`ENGINE_LOCK_KEY`, TTL 30s) antes de cada ciclo de análisis/ejecución, para que dos instancias del servicio (por un despliegue accidental duplicado) nunca operen en simultáneo sobre la misma cuenta.

## Validación de inputs

Todos los endpoints usan modelos Pydantic — nunca se parsean payloads a mano. Los límites de exchange (tick size, lot size, min notional) se validan localmente antes de enviar cualquier orden real.

## Superficie expuesta

Solo el backend (puerto 8000) y el frontend (puerto 5173, vía nginx) exponen puertos al host en `docker-compose.yml`; PostgreSQL y Redis solo son alcanzables dentro de la red interna de Docker.

## Qué NO cubre esta versión

- No hay multi-usuario ni control de acceso por roles (fuera de alcance: uso interno de una sola persona).
- No hay 2FA.
- CSRF: mitigado por `samesite=lax` en la cookie de sesión; no hay un token CSRF explícito adicional (aceptable para un backend de un solo origen, sin formularios cross-site).
