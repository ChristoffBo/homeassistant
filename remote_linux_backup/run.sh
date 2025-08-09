#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

# Read options
UI_PORT=$(jq -r '.ui_port // 8066' $CONFIG_PATH)

echo "[INFO] Starting Remote Linux Backup on port ${UI_PORT}"

# Start API
python3 /app/api.py --port "${UI_PORT}" --config "${CONFIG_PATH}" &
API_PID=$!

# Start scheduler
python3 /app/scheduler.py --config "${CONFIG_PATH}" &
SCHED_PID=$!

# Wait for processes
wait ${API_PID} ${SCHED_PID}
