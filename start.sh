#!/usr/bin/env bash
# Build + start cả SearXNG và FastAPI server qua docker compose.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_API_PORT="${API_PORT:-18899}"

pick_port() {
  local preferred="$1"
  local fallback="$2"
  if command -v ss >/dev/null 2>&1 && ss -ltn "( sport = :${preferred} )" | grep -q LISTEN; then
    echo "${fallback}"
    return
  fi
  echo "${preferred}"
}

API_PORT="$(pick_port "${DEFAULT_API_PORT}" "18899")"
export API_PORT

cd "${DIR}"
docker compose up -d --build

echo "[wait] api http://localhost:${API_PORT} ..."
for i in $(seq 1 30); do
  if curl -fsS "http://localhost:${API_PORT}/search" \
    -H "Content-Type: application/json" \
    -d '{"question":"healthcheck","limit":1}' >/dev/null 2>&1; then
    echo "[ok] api ready: http://localhost:${API_PORT}"
    exit 0
  fi
  sleep 1
done

echo "[err] timeout waiting. docker compose logs" >&2
exit 1
