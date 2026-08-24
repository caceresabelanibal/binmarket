#!/usr/bin/env bash
# Spins up throwaway Postgres + Redis containers, runs the backend/shared
# pytest suite against them, then tears everything down. Safe to run
# repeatedly; never touches the project's real .env or docker-compose stack.
set -euo pipefail

PG_CONTAINER=binmarket-test-pg
REDIS_CONTAINER=binmarket-test-redis
PG_PORT=55432
REDIS_PORT=56379

cleanup() {
  docker rm -f "$PG_CONTAINER" "$REDIS_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker run -d --name "$PG_CONTAINER" -e POSTGRES_DB=binmarket_test -e POSTGRES_USER=binmarket \
  -e POSTGRES_PASSWORD=binmarket -p "$PG_PORT":5432 postgres:16-alpine >/dev/null
docker run -d --name "$REDIS_CONTAINER" -p "$REDIS_PORT":6379 redis:7-alpine >/dev/null

echo "Waiting for Postgres..."
for _ in $(seq 1 30); do
  docker exec "$PG_CONTAINER" pg_isready -U binmarket >/dev/null 2>&1 && break
  sleep 1
done

export POSTGRES_HOST=localhost POSTGRES_PORT=$PG_PORT POSTGRES_DB=binmarket_test
export POSTGRES_USER=binmarket POSTGRES_PASSWORD=binmarket
export REDIS_URL="redis://localhost:${REDIS_PORT}/0"
export SECRET_KEY=test-secret-key
export ADMIN_PASSWORD=test-admin-password

cd "$(dirname "$0")/.."
python -m pytest tests "$@"
