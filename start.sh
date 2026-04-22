#!/usr/bin/env bash
# Build + start cả SearXNG và FastAPI server qua docker compose.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SEARXNG_PORT="${SEARXNG_PORT:-8888}"
API_PORT="${API_PORT:-8899}"

cd "${DIR}"
docker compose up -d --build

echo "[wait] searxng http://localhost:${SEARXNG_PORT} ..."
for i in $(seq 1 30); do
  if curl -fsS "http://localhost:${SEARXNG_PORT}/search?q=test&format=json" >/dev/null 2>&1; then
    echo "[ok] searxng ready"
    break
  fi
  sleep 1
done

echo "[wait] api http://localhost:${API_PORT} ..."
for i in $(seq 1 30); do
  if curl -fsS "http://localhost:${API_PORT}/health" >/dev/null 2>&1; then
    echo "[ok] api ready: http://localhost:${API_PORT}"
    exit 0
  fi
  sleep 1
done

echo "[err] timeout waiting. docker compose logs" >&2
exit 1
