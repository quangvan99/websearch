#!/usr/bin/env bash
# Exec websearch.py bên trong container api. Mặc định: "giá vàng SJC hôm nay".
# Usage:
#   ./run.sh                            # câu mặc định
#   ./run.sh "giá xăng hôm nay"         # câu tuỳ ý
#   ./run.sh --raw "..."                # chỉ trả kết quả search, bỏ qua LLM
#   ./run.sh --no-fetch "..."           # tắt trafilatura (chỉ dùng snippet)
#   ./run.sh --max-chars 6000 "..."     # cắt mỗi trang N ký tự (0 = không cắt)
# Mặc định: fetch=ON, max_chars=4000
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_Q="giá vàng SJC hôm nay"

if [ "$#" -eq 0 ]; then
  set -- "${DEFAULT_Q}"
fi

cd "${DIR}"
exec docker compose exec -T api python3 websearch.py "$@"
