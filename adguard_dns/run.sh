#!/usr/bin/env sh
set -eu

# Read HA options
OPTS="/data/options.json"
DNS_PORT=53
SETUP_PORT=3000
WEB_PORT=80
if [ -s "$OPTS" ]; then
  get_int() { grep -oE "\"$1\"\\s*:\\s*[0-9]+" "$OPTS" 2>/dev/null | sed 's/[^0-9]//g' || true; }
  _d="$(get_int dns_port)";   [ -n "${_d:-}" ] && DNS_PORT="$_d"
  _s="$(get_int setup_port)"; [ -n "${_s:-}" ] && SETUP_PORT="$_s"
  _w="$(get_int web_port)";   [ -n "${_w:-}" ] && WEB_PORT="$_w"
fi

# Persist under /config (because your config.json maps "config:rw")
CONF_DIR="/config/adguard"
WORK_DIR="/config/adguard/work"
mkdir -p "$CONF_DIR" "$WORK_DIR"
chmod 700 "$WORK_DIR" || true

CONF_FILE="$CONF_DIR/AdGuardHome.yaml"

# Decide which web port to serve:
# - First run (no config yet) → serve setup wizard on SETUP_PORT
# - After setup (config file present) → serve on WEB_PORT
if [ ! -s "$CONF_FILE" ]; then
  WEB_ADDR="0.0.0.0:${SETUP_PORT}"
else
  WEB_ADDR="0.0.0.0:${WEB_PORT}"
fi

# Start AdGuard Home with explicit persistent paths and web address.
# DNS port is managed inside the YAML after the wizard;
# host port mappings are defined in config.json "ports".
exec /opt/adguardhome/AdGuardHome \
  --work-dir "$WORK_DIR" \
  --config   "$CONF_FILE" \
  --web-addr "$WEB_ADDR"