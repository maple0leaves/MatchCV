#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.production}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/docker-compose.prod.yml")

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

value_of() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'
}

require_secret() {
  local key="$1" min_length="$2" forbidden="${3:-}"
  local value
  value="$(value_of "$key")"
  [[ -n "$value" ]] || fail "$key 未填写"
  [[ ${#value} -ge $min_length ]] || fail "$key 至少需要 $min_length 位"
  [[ -z "$forbidden" || "$value" != "$forbidden" ]] || fail "$key 仍在使用默认值"
  [[ "$value" != replace-* ]] || fail "$key 仍是示例占位符"
}

command -v docker >/dev/null || fail "未安装 Docker"
docker compose version >/dev/null || fail "未安装 Docker Compose v2"
[[ -f "$ENV_FILE" ]] || fail "找不到配置文件：$ENV_FILE"
[[ -f "$ROOT_DIR/deploy/Caddyfile" ]] || fail "缺少 deploy/Caddyfile"
[[ -f "$ROOT_DIR/deploy/rocketmq/broker.conf" ]] || fail "缺少 RocketMQ broker.conf"

scheme="$(value_of APP_SCHEME)"
scheme="${scheme:-https}"
[[ "$scheme" == "http" || "$scheme" == "https" ]] || fail "APP_SCHEME 只能是 http 或 https"

domain="$(value_of APP_DOMAIN)"
is_domain=false
is_ipv4=false
if [[ "$domain" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
  is_domain=true
elif [[ "$domain" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  IFS=. read -r ip1 ip2 ip3 ip4 <<< "$domain"
  if (( ip1 <= 255 && ip2 <= 255 && ip3 <= 255 && ip4 <= 255 )); then
    is_ipv4=true
  fi
fi

[[ "$is_domain" == true || "$is_ipv4" == true ]] || fail "APP_DOMAIN 必须是有效域名或公网 IPv4 地址"
[[ "$scheme" != "https" || "$is_domain" == true ]] || fail "当前 Caddy 配置的 https 模式需要域名；临时公网 IP 请使用 APP_SCHEME=http"
require_secret JWT_SECRET 32 "change-me-in-production-use-random-32-bytes"
require_secret INTERNAL_SERVICE_TOKEN 32 "dev-internal-token-change-in-production"
require_secret MYSQL_PASSWORD 16 "hellojobs123"
require_secret PGVECTOR_PASSWORD 16 "matchcv"
require_secret ADMIN_PASSWORD 12 "admin123"
require_secret OPENAI_API_KEY 8

jwt_secret="$(value_of JWT_SECRET)"
internal_token="$(value_of INTERNAL_SERVICE_TOKEN)"
[[ "$jwt_secret" != "$internal_token" ]] || fail "JWT_SECRET 与 INTERNAL_SERVICE_TOKEN 不能相同"

available_kb="$(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $4}')"
[[ "$available_kb" -ge 10485760 ]] || fail "磁盘可用空间不足 10 GiB"
if [[ -r /proc/meminfo ]]; then
  memory_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  [[ "$memory_kb" -ge 7340032 ]] || fail "建议至少 7 GiB 内存"
fi

"${COMPOSE[@]}" config --quiet
echo "OK: 生产配置、密钥长度、主机资源和 Compose 语法检查通过。"
