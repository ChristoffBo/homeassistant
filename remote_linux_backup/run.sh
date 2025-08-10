#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/data/options.json"

# Ensure required directories for persistent data
mkdir -p /config/remote_linux_backup/backups
mkdir -p /config/remote_linux_backup/logs
mkdir -p /config/remote_linux_backup/state

TZVAL="$(jq -r '.timezone // "Africa/Johannesburg"' "$CONFIG_PATH" 2>/dev/null || echo "Africa/Johannesburg")"
export TZ="$TZVAL"

PORT="$(jq -r '.ui_port // 8066' "$CONFIG_PATH" 2>/dev/null || echo "8066")"
export RLB_STORAGE_PATH="$(jq -r '.storage_path // "/config/remote_linux_backup/backups"' "$CONFIG_PATH" 2>/dev/null || echo "/config/remote_linux_backup/backups")"
export RLB_GOTIFY_URL="$(jq -r '.gotify_url // ""' "$CONFIG_PATH" 2>/dev/null || echo "")"
export RLB_GOTIFY_TOKEN="$(jq -r '.gotify_token // ""' "$CONFIG_PATH" 2>/dev/null || echo "")"
export RLB_AUTO_CHECK_HOURS="$(jq -r '.auto_check_interval_hours // 0' "$CONFIG_PATH" 2>/dev/null || echo "0")"

echo "[RLB] Starting Remote Linux Backup on port $PORT (TZ=$TZ)"
exec python3 /app/server.py --port "$PORT"
