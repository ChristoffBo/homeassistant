#!/usr/bin/env bash
set -euo pipefail
PORT=$(jq -r '.port // 8066' /data/options.json 2>/dev/null || echo 8066)
export TZ="${TZ:-UTC}"
echo "[RLB] Starting on port $PORT (TZ=$TZ)"
exec /opt/venv/bin/python /app/server.py --port "$PORT"
