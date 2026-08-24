#!/usr/bin/env bash
# Restores a .sql.gz dump produced by backup-db.sh into the running
# docker-compose Postgres. DESTRUCTIVE: drops and recreates all tables.
# Usage: ./scripts/restore-db.sh ./backups/binmarket_20260101_120000.sql.gz
set -euo pipefail

cd "$(dirname "$0")/.."
DUMP_FILE="${1:?Usage: restore-db.sh <dump-file.sql.gz>}"

set -a
source .env
set +a

read -p "This will OVERWRITE the current database '$POSTGRES_DB'. Type 'yes' to continue: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

echo "Restoring $DUMP_FILE into '$POSTGRES_DB' ..."
gunzip -c "$DUMP_FILE" | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
echo "Restore complete."
