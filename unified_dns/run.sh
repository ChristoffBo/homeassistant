#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
PORT=$(jq -r '.listen_port // 8067' "$CONFIG_PATH" 2>/dev/null || echo 8067)

echo "[Unified DNS] Starting container on port ${PORT}"

# Best-effort apt maintenance at runtime; continue if offline
(apt-get update || echo "[Unified DNS] apt-get update failed (offline?)") >/dev/null 2>&1 || true
(apt-get -y upgrade || echo "[Unified DNS] apt-get upgrade failed (offline?)") >/dev/null 2>&1 || true

exec python3 /app/server.py --port "${PORT}"
