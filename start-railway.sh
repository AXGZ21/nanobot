#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${HOME}/.nanobot"

PORT="${PORT:-8080}"
echo "Starting nanobot control plane on port ${PORT}"
exec uvicorn webui.main:app --host 0.0.0.0 --port "${PORT}"
