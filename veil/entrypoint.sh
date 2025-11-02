#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/app"
DATA_DIR="/data"
SHARE_DIR="/share/veil"
CONFIG_DIR="/config"
DEFAULT_OPTS="${APP_DIR}/options.json"
OPTIONS_FILE="${DATA_DIR}/options.json"

mkdir -p "${DATA_DIR}" "${SHARE_DIR}" "${CONFIG_DIR}" /var/log/veil
chown -R root:root "${DATA_DIR}" "${SHARE_DIR}" "${CONFIG_DIR}" /var/log/veil

if [ ! -f "${OPTIONS_FILE}" ]; then
  echo "Creating default options.json in /data..."
  cp -a "${DEFAULT_OPTS}" "${OPTIONS_FILE}"
  chmod 600 "${OPTIONS_FILE}"
fi

# 🔗 Symlink for legacy path expectations
ln -sf "${OPTIONS_FILE}" "${CONFIG_DIR}/options.json"
cp -f "${OPTIONS_FILE}" "${SHARE_DIR}/options.json"

echo "🧩 Starting Veil (config: ${OPTIONS_FILE})"
exec "$@"
