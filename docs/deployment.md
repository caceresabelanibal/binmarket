# Despliegue en otro servidor

La aplicación no depende de rutas ni configuraciones específicas de la máquina de desarrollo — todo lo que varía entre entornos vive en `.env`.

## Pasos

```bash
git clone <url-del-repositorio>
cd binmarket
cp .env.example .env
nano .env   # completar SECRET_KEY, ADMIN_PASSWORD, POSTGRES_PASSWORD, Binance, etc.
docker compose up -d --build
```

Eso es todo — no se requiere editar código ni `docker-compose.yml` para un despliegue estándar.

## Actualizar desde GitHub

```bash
git pull
docker compose up -d --build
```

Docker Compose reconstruye solo las imágenes cuyo contexto cambió. Las migraciones de Alembic corren automáticamente al arrancar el backend (`backend/entrypoint.sh`), así que un `git pull` que incluya una migración nueva se aplica sola.

## Backup / restore de PostgreSQL

```bash
./scripts/backup-db.sh                      # crea ./backups/binmarket_<timestamp>.sql.gz
./scripts/restore-db.sh ./backups/archivo.sql.gz
```

(Hay equivalentes `.ps1` para PowerShell.) Recomendado antes de cualquier actualización mayor o cambio de servidor.

## Migrar a otro servidor

1. `./scripts/backup-db.sh` en el servidor origen.
2. Copiar el `.sql.gz` y el `.env` (con las credenciales reales) al servidor destino.
3. `git clone` + `docker compose up -d --build` en el destino (esto crea una base vacía).
4. `./scripts/restore-db.sh <archivo>` para restaurar los datos.

## Reverse proxy / TLS

El `docker-compose.yml` expone el frontend en el puerto 5173 y el backend en 8000 directamente. Para exponerlo en internet con HTTPS, poner un reverse proxy (Caddy, Traefik, nginx) por delante del puerto 5173 únicamente (el frontend ya proxea `/api` y `/ws` internamente) y no exponer el puerto 8000 del backend directamente.

## Actualizar el modo de un despliegue existente

Los cambios de modo (`PAPER` → `TESTNET` → `LIVE`) se hacen siempre desde la UI (`Settings → Modo de operación`), nunca editando la base de datos a mano — ese flujo es el que aplica las confirmaciones de seguridad de la sección `docs/security.md`.
