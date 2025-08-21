#!/usr/bin/env sh
set -eu

OPTS="/data/options.json"
WEB_PORT=3000
DNS_PORT=5353
if [ -s "$OPTS" ]; then
  WP=$(grep -oE '"web_port"\s*:\s*[0-9]+' "$OPTS" 2>/dev/null | sed 's/[^0-9]//g' || true)
  DP=$(grep -oE '"dns_port"\s*:\s*[0-9]+' "$OPTS" 2>/dev/null | sed 's/[^0-9]//g' || true)
  [ -n "${WP:-}" ] && WEB_PORT="$WP"
  [ -n "${DP:-}" ] && DNS_PORT="$DP"
fi

CONF_DIR="/data/conf"
WORK_DIR="/data/work"
mkdir -p "$CONF_DIR" "$WORK_DIR"

WEB_ADDR="0.0.0.0:${WEB_PORT}"

exec /opt/adguardhome/AdGuardHome \
  --work-dir "$WORK_DIR" \
  --config   "$CONF_DIR/AdGuardHome.yaml" \
  --web-addr "$WEB_ADDR"