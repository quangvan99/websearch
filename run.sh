#!/usr/bin/env bash
# Exec websearch.py bên trong container api. Mặc định: "giá vàng SJC hôm nay".
# Usage:
#   ./run.sh                      # câu mặc định
#   ./run.sh "giá xăng hôm nay"  # câu tuỳ ý
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_Q="giá vàng SJC hôm nay"

if [ "$#" -eq 0 ]; then
  Q="${DEFAULT_Q}"
else
  Q="$*"
fi

cd "${DIR}"
exec docker compose exec -T api python3 websearch.py "${Q}"
