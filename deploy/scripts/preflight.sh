#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.production}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml")

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
  [[ -n "$value" ]] || fail "$key is missing"
  [[ ${#value} -ge $min_length ]] || fail "$key must contain at least $min_length characters"
  [[ -z "$forbidden" || "$value" != "$forbidden" ]] || fail "$key still uses a forbidden default"
  [[ "$value" != replace-* ]] || fail "$key still contains an example placeholder"
}

command -v docker >/dev/null || fail "Docker is not installed"
docker compose version >/dev/null || fail "Docker Compose v2 is not installed"
[[ -f "$ENV_FILE" ]] || fail "Environment file not found: $ENV_FILE"

shared_network="$(value_of SHARED_NETWORK)"
shared_network="${shared_network:-shared-platform}"
docker network inspect "$shared_network" >/dev/null 2>&1 ||
  fail "Shared Docker network '$shared_network' does not exist; start Project-Deployment first"

scheme="$(value_of APP_SCHEME)"
scheme="${scheme:-https}"
[[ "$scheme" == "http" || "$scheme" == "https" ]] ||
  fail "APP_SCHEME must be http or https"

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

[[ "$is_domain" == true || "$is_ipv4" == true ]] ||
  fail "APP_DOMAIN must be a valid domain name or public IPv4 address"
[[ "$scheme" != "https" || "$is_domain" == true ]] ||
  fail "HTTPS mode requires a domain; use APP_SCHEME=http for temporary public-IP testing"

require_secret JWT_SECRET 32 "change-me-in-production-use-random-32-bytes"
require_secret INTERNAL_SERVICE_TOKEN 32 "dev-internal-token-change-in-production"
require_secret MYSQL_PASSWORD 16 "hellojobs123"
require_secret REDIS_PASSWORD 16
require_secret PGVECTOR_PASSWORD 16 "matchcv"
require_secret ADMIN_PASSWORD 12 "admin123"
require_secret OPENAI_API_KEY 8
require_secret LLM_FALLBACK_API_KEY 8
require_secret EMBEDDING_API_KEY 8

for required_setting in \
  OPENAI_BASE_URL \
  LLM_MODEL \
  LLM_FALLBACK_BASE_URL \
  LLM_FALLBACK_MODEL \
  EMBEDDING_BASE_URL \
  EMBEDDING_MODEL; do
  [[ -n "$(value_of "$required_setting")" ]] || fail "$required_setting is missing"
done

matchcv_data_dir="$(value_of MATCHCV_DATA_DIR)"
[[ "$matchcv_data_dir" == /* ]] || fail "MATCHCV_DATA_DIR must be an absolute server path"

jwt_secret="$(value_of JWT_SECRET)"
internal_token="$(value_of INTERNAL_SERVICE_TOKEN)"
[[ "$jwt_secret" != "$internal_token" ]] ||
  fail "JWT_SECRET and INTERNAL_SERVICE_TOKEN must be different"

available_kb="$(df -Pk "$(dirname "$matchcv_data_dir")" | awk 'NR==2 {print $4}')"
[[ "$available_kb" -ge 10485760 ]] || fail "The data disk must have at least 10 GiB available"

if [[ -r /proc/meminfo ]]; then
  memory_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  [[ "$memory_kb" -ge 7340032 ]] ||
    fail "MatchCV requires at least 7 GiB of visible memory (an 8 GB ECS size)"
fi

"${COMPOSE[@]}" config --quiet
echo "OK: MatchCV production preflight passed."
