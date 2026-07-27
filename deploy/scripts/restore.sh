#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.production}"
BACKUP_DIR="${2:-}"
BACKUP_ROOT="$(realpath -m "${BACKUP_ROOT:-$ROOT_DIR/backups}")"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml")

[[ "${RESTORE_CONFIRM:-}" == "restore" ]] || {
  echo "ERROR: 恢复会覆盖当前数据。确认后使用 RESTORE_CONFIRM=restore 运行。" >&2
  exit 1
}
[[ -n "$BACKUP_DIR" ]] || { echo "ERROR: 请提供备份目录" >&2; exit 1; }
BACKUP_DIR="$(realpath "$BACKUP_DIR")"
[[ "$BACKUP_DIR" == "$BACKUP_ROOT"/* ]] || {
  echo "ERROR: 备份目录必须位于 $BACKUP_ROOT 内" >&2
  exit 1
}
for file in mysql.sql pgvector.sql app-data.tar.gz SHA256SUMS; do
  [[ -f "$BACKUP_DIR/$file" ]] || { echo "ERROR: 缺少 $file" >&2; exit 1; }
done
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS --ignore-missing)

restart_apps() {
  "${COMPOSE[@]}" start ai-service java-backend >/dev/null 2>&1 || true
}
trap restart_apps EXIT

"${COMPOSE[@]}" stop java-backend ai-service
docker exec -i shared-mysql sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" hellojobs' \
  < "$BACKUP_DIR/mysql.sql"
docker exec -i shared-pgvector sh -c \
  'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" resume_vectors' \
  < "$BACKUP_DIR/pgvector.sql"
"${COMPOSE[@]}" run --rm --no-deps -T ai-service sh -c \
  'find /app/data/resumes /app/data/vector_store /app/data/checkpoints -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -C /app/data -xzf -' \
  < "$BACKUP_DIR/app-data.tar.gz"

restart_apps
trap - EXIT
echo "OK: 已从 $BACKUP_DIR 恢复；请立即运行 smoke-test.sh。"
