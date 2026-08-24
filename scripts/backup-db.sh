#!/usr/bin/env bash
# Dumps the running docker-compose Postgres to a timestamped .sql.gz file in
# ./backups/. Usage: ./scripts/backup-db.sh [output-directory]
set -euo pipefail

cd "$(dirname "$0")/.."
OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"

set -a
source .env
set +a

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_FILE="$OUT_DIR/binmarket_${TIMESTAMP}.sql.gz"

echo "Dumping database '$POSTGRES_DB' to $OUT_FILE ..."
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "$OUT_FILE"
echo "Done: $OUT_FILE"
