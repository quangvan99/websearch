#!/usr/bin/env bash
# Query plugin discovery-only search từ trong container api.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_Q="latest PostgreSQL 17 release notes"

if [ "$#" -eq 0 ]; then
  set -- "${DEFAULT_Q}"
fi

cd "${DIR}"
exec docker compose exec -T api python3 websearch.py "$@"
