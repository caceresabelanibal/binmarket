#!/bin/sh
set -e
echo "[marketpulse] starting API server (seeding + background ingest run in-process on startup)..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
