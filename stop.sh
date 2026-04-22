#!/usr/bin/env bash
# Dừng và xoá stack (searxng + api).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${DIR}"
docker compose down
