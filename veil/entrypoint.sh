#!/usr/bin/env bash
set -euo pipefail

DEFAULT_OPTS="/app/options.json"
CONFIG_DIR="/config"
OPTIONS_FILE="${CONFIG_DIR}/options.json"

mkdir -p "${CONFIG_DIR}" /var/log/veil
chown -R root:root "${CONFIG_DIR}" /var/log/veil

# ensure default options exist
if [ ! -f "${OPTIONS_FILE}" ]; then
  echo "Creating default options.json..."
  cp -a "${DEFAULT_OPTS}" "${OPTIONS_FILE}"
  chmod 600 "${OPTIONS_FILE}"
fi

# ===== persistent blocklist under /share =====
SHARE_DIR="/share/veil"
SHARE_BLOCKLIST="${SHARE_DIR}/veil_blocklists.json"
CONFIG_BLOCKLIST="/config/veil_blocklists.json"

mkdir -p "${SHARE_DIR}"

# migrate existing once
if [ -f "${CONFIG_BLOCKLIST}" ] && [ ! -f "${SHARE_BLOCKLIST}" ]; then
  mv "${CONFIG_BLOCKLIST}" "${SHARE_BLOCKLIST}"
fi

# ensure exists
if [ ! -f "${SHARE_BLOCKLIST}" ]; then
  echo '{"blocklist":[],"blacklist":[],"whitelist":[],"blocklist_count":0,"blacklist_count":0,"whitelist_count":0,"last_update":0,"timestamp":0}' > "${SHARE_BLOCKLIST}"
fi

# always symlink so internal code sees /config/veil_blocklists.json
ln -sf "${SHARE_BLOCKLIST}" "${CONFIG_BLOCKLIST}"

echo "🧩 Starting Veil (config: ${OPTIONS_FILE})"
exec "$@"
