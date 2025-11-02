#!/usr/bin/env bash
set -euo pipefail

# Directories
APP_DIR="/app"
DATA_DIR="/data"
SHARE_DIR="/share/veil"
CONFIG_DIR="/config"
DEFAULT_OPTS="${APP_DIR}/options.json"
OPTIONS_FILE="${DATA_DIR}/options.json"

# Ensure directories exist and have proper permissions
mkdir -p "${DATA_DIR}" "${SHARE_DIR}" "${CONFIG_DIR}" /var/log/veil
chown -R root:root "${DATA_DIR}" "${SHARE_DIR}" "${CONFIG_DIR}" /var/log/veil

# If no options.json in /data, initialize it from the built-in default
if [ ! -f "${OPTIONS_FILE}" ]; then
  echo "Creating default options.json in /data..."
  cp -a "${DEFAULT_OPTS}" "${OPTIONS_FILE}"
  chmod 600 "${OPTIONS_FILE}"
fi

# Also keep a copy in /share for external inspection/backups
cp -f "${OPTIONS_FILE}" "${SHARE_DIR}/options.json"

echo "🧩 Starting Veil (config: ${OPTIONS_FILE})"
exec "$@"
