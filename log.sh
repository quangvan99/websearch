#!/usr/bin/env bash
# Xem log container searxng. -f để follow.
set -euo pipefail

NAME="searxng"

if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--follow" ]; then
  docker logs -f --tail 100 "${NAME}"
else
  docker logs --tail 200 "${NAME}"
fi
