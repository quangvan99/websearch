#!/usr/bin/env bash
# Start SearXNG in docker (JSON API enabled, listen localhost:8888).
set -euo pipefail

NAME="searxng"
PORT="${SEARXNG_PORT:-8888}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${DIR}/searxng"

if [ ! -f "${CONFIG_DIR}/settings.yml" ]; then
  echo "Missing ${CONFIG_DIR}/settings.yml" >&2
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${NAME}$"; then
  echo "[searxng] container exists -> start & restart"
  docker start "${NAME}" >/dev/null
  docker restart "${NAME}" >/dev/null
else
  echo "[searxng] creating new container on :${PORT}"
  docker run -d \
    --name "${NAME}" \
    -p "${PORT}:8080" \
    -v "${CONFIG_DIR}:/etc/searxng" \
    --restart unless-stopped \
    searxng/searxng >/dev/null
fi

echo "[searxng] waiting for http://localhost:${PORT} ..."
for i in $(seq 1 30); do
  if curl -fsS "http://localhost:${PORT}/search?q=test&format=json" >/dev/null 2>&1; then
    echo "[searxng] ready: http://localhost:${PORT}"
    exit 0
  fi
  sleep 1
done

echo "[searxng] timeout waiting for JSON API. Kiểm tra: docker logs ${NAME}" >&2
exit 1
