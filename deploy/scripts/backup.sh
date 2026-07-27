#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.production}"
BACKUP_ROOT="${BACKUP_ROOT:-$ROOT_DIR/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml")

mkdir -p "$DEST"
chmod 700 "$DEST"

restart_apps() {
  "${COMPOSE[@]}" start ai-service java-backend >/dev/null 2>&1 || true
}
trap restart_apps EXIT

"${COMPOSE[@]}" stop java-backend ai-service
docker exec -i shared-mysql sh -c \
  'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --events hellojobs' \
  > "$DEST/mysql.sql"
docker exec -i shared-pgvector sh -c \
  'exec pg_dump --clean --if-exists -U "$POSTGRES_USER" resume_vectors' \
  > "$DEST/pgvector.sql"
"${COMPOSE[@]}" run --rm --no-deps -T ai-service \
  tar -C /app/data -czf - resumes vector_store checkpoints \
  > "$DEST/app-data.tar.gz"

cp "$ENV_FILE" "$DEST/env.production.snapshot"
chmod 600 "$DEST/env.production.snapshot"
(cd "$DEST" && sha256sum mysql.sql pgvector.sql app-data.tar.gz env.production.snapshot > SHA256SUMS)

restart_apps
trap - EXIT
echo "OK: 备份已写入 $DEST"
