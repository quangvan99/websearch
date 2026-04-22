#!/usr/bin/env bash
# Stop và xóa SearXNG container.
set -euo pipefail

NAME="searxng"

if ! docker ps -a --format '{{.Names}}' | grep -q "^${NAME}$"; then
  echo "[searxng] không tìm thấy container '${NAME}'"
  exit 0
fi

echo "[searxng] stopping..."
docker stop "${NAME}" >/dev/null || true
echo "[searxng] removing..."
docker rm "${NAME}" >/dev/null || true
echo "[searxng] done"
