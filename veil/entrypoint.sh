#!/usr/bin/env bash
set -euo pipefail

DEFAULT_OPTS="/app/options.json"

CONFIG_DIR="/config"
SHARE_DIR="/share/veil"
OPTIONS_FILE="${CONFIG_DIR}/options.json"
SHARE_OPTIONS="${SHARE_DIR}/options.json"

mkdir -p "${CONFIG_DIR}" "${SHARE_DIR}" /var/log/veil
chown -R root:root "${CONFIG_DIR}" /var/log/veil "${SHARE_DIR}"

# ===== ensure persistent options.json =====
if [ -f "${CONFIG_DIR}/options.json" ] && [ ! -f "${SHARE_OPTIONS}" ]; then
  echo "Migrating existing /config/options.json to /share/veil..."
  mv "${CONFIG_DIR}/options.json" "${SHARE_OPTIONS}"
fi

# first run — copy defaults
if [ ! -f "${SHARE_OPTIONS}" ]; then
  echo "Creating default /share/veil/options.json..."
  cp -a "${DEFAULT_OPTS}" "${SHARE_OPTIONS}"
  chmod 600 "${SHARE_OPTIONS}"
fi

# symlink so HA and backend both point to /share
ln -sf "${SHARE_OPTIONS}" "${OPTIONS_FILE}"

# ===== ensure persistent blocklist =====
SHARE_BLOCKLIST="${SHARE_DIR}/veil_blocklists.json"
CONFIG_BLOCKLIST="${CONFIG_DIR}/veil_blocklists.json"

if [ -f "${CONFIG_BLOCKLIST}" ] && [ ! -f "${SHARE_BLOCKLIST}" ]; then
  mv "${CONFIG_BLOCKLIST}" "${SHARE_BLOCKLIST}"
fi

if [ ! -f "${SHARE_BLOCKLIST}" ]; then
  echo '{"blocklist":[],"blacklist":[],"whitelist":[],"blocklist_count":0,"blacklist_count":0,"whitelist_count":0,"last_update":0,"timestamp":0}' > "${SHARE_BLOCKLIST}"
fi

ln -sf "${SHARE_BLOCKLIST}" "${CONFIG_BLOCKLIST}"

echo "🧩 Starting Veil (persistent config: ${SHARE_OPTIONS})"
exec "$@"
