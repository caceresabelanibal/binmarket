#!/bin/sh
set -e

echo "[backend] running database migrations..."
alembic -c /app/database/alembic.ini upgrade head

echo "[backend] seeding admin user and default settings..."
python -m app.seed

echo "[backend] starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
