#!/usr/bin/env bash
# Xem log docker compose. ./log.sh -f để follow. ./log.sh <service> để lọc.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${DIR}"

if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--follow" ]; then
  shift
  exec docker compose logs -f --tail 100 "$@"
fi
exec docker compose logs --tail 200 "$@"
