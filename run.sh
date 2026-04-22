#!/usr/bin/env bash
# Chạy websearch.py với câu hỏi. Mặc định: "giá vàng SJC hôm nay".
# Usage:
#   ./run.sh                         # dùng câu mặc định
#   ./run.sh "giá xăng hôm nay"     # câu tuỳ ý
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_Q="giá vàng SJC hôm nay"

if [ "$#" -eq 0 ]; then
  Q="${DEFAULT_Q}"
else
  Q="$*"
fi

exec python3 "${DIR}/websearch.py" "${Q}"
