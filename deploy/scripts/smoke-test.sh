#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.production}"
DOMAIN="$(sed -n 's/^APP_DOMAIN=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
SCHEME="$(sed -n 's/^APP_SCHEME=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
SCHEME="${SCHEME:-https}"
ADMIN_USERNAME="$(sed -n 's/^ADMIN_USERNAME=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
ADMIN_PASSWORD="$(sed -n 's/^ADMIN_PASSWORD=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
BASE_URL="$SCHEME://$DOMAIN"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml")

[[ -n "$DOMAIN" && -n "$SCHEME" && -n "$ADMIN_USERNAME" && -n "$ADMIN_PASSWORD" ]] || {
  echo "ERROR: .env.production 缺少访问地址或管理员凭据" >&2
  exit 1
}

curl --fail --silent --show-error "$BASE_URL/api/health" |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ok"'

login_body="$(
  ADMIN_USERNAME="$ADMIN_USERNAME" ADMIN_PASSWORD="$ADMIN_PASSWORD" python3 -c \
    'import json,os; print(json.dumps({"username":os.environ["ADMIN_USERNAME"],"password":os.environ["ADMIN_PASSWORD"]}))'
)"
token="$(
  curl --fail --silent --show-error \
    -H 'Content-Type: application/json' \
    --data "$login_body" \
    "$BASE_URL/api/auth/login" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
)"

curl --fail --silent --show-error \
  -H "Authorization: Bearer $token" \
  "$BASE_URL/api/auth/me" |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["sub"]'
curl --fail --silent --show-error \
  -H "Authorization: Bearer $token" \
  "$BASE_URL/api/students?page=1&page_size=1" |
  python3 -c 'import json,sys; data=json.load(sys.stdin); assert "items" in data and "total" in data'

"${COMPOSE[@]}" ps
echo "OK: HTTPS、健康检查、登录和候选人列表冒烟检查通过。"
