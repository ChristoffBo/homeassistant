#!/usr/bin/env bash
set -euo pipefail

DEFAULT_OPTS="/app/default_options.json"
CONFIG_DIR="/config"
OPTIONS_FILE="${CONFIG_DIR}/options.json"

mkdir -p "${CONFIG_DIR}" /var/log/veil
chown -R root:root "${CONFIG_DIR}" /var/log/veil

if [ ! -f "${OPTIONS_FILE}" ]; then
  echo "Creating default options.json..."
  cp -a "${DEFAULT_OPTS}" "${OPTIONS_FILE}"
  chmod 600 "${OPTIONS_FILE}"
fi

echo "🧩 Starting Veil (config: ${OPTIONS_FILE})"
exec "$@"
