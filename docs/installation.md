# Instalación

## Requisitos

- Docker Engine 24+ y Docker Compose v2 (`docker compose version`).
- Una cuenta de Binance (opcional para empezar: la app arranca en modo **PAPER** sin necesidad de credenciales).

## Pasos

```bash
git clone <url-del-repositorio> binmarket
cd binmarket
cp .env.example .env
```

Editar `.env` y como mínimo cambiar:

- `SECRET_KEY` (cualquier cadena larga y aleatoria)
- `ADMIN_PASSWORD`
- `POSTGRES_PASSWORD`

El resto de las variables tienen valores por defecto seguros (modo `testnet`, sin API keys, Paper Trading implícito).

```bash
docker compose up -d --build
```

La primera vez esto:

1. Construye las 4 imágenes propias (`backend`, `market-data`, `trading-engine`, `frontend`).
2. Levanta PostgreSQL y Redis, espera a que estén healthy.
3. El backend corre las migraciones de Alembic y siembra el usuario admin + configuración por defecto (modo PAPER, bot apagado).
4. Levanta `market-data` y `trading-engine` una vez que el backend está saludable.

Verificar que todo esté arriba:

```bash
docker compose ps
curl http://localhost:8000/readiness
```

Abrir el navegador en **http://localhost:5173** e iniciar sesión con el usuario/contraseña definidos en `.env`.

## Primer uso

Al entrar por primera vez, `Settings → Asistente` guía paso a paso: conexión a Binance, selección de pares, descarga de histórico, revisión de estrategia, configuración de riesgo, backtest, Paper Trading, Testnet y finalmente LIVE (sección 42/43 del pedido original — "Modo Safe Start"). La aplicación arranca siempre en:

```
PAPER TRADING = activo (modo)
TRADING AUTOMÁTICO = OFF (bot apagado)
```

Nada se ejecuta contra el mercado hasta encender el bot explícitamente desde el botón de la barra superior.

## Desarrollo local (hot reload)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Esto monta el código fuente de `backend`, `trading-engine`, `market-data` y `frontend/src` como volúmenes y usa `uvicorn --reload` / `vite dev` en lugar de las imágenes de producción.

## Correr los tests

```bash
# backend / shared (pytest, levanta y destruye Postgres+Redis temporales)
./scripts/run-tests.sh        # Linux/macOS/Git Bash
./scripts/run-tests.ps1       # PowerShell

# frontend (vitest)
cd frontend && npm install && npm test
```
