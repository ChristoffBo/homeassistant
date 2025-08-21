#!/usr/bin/env bash
set -e

CONF="/config/dnscrypt-proxy.toml"
OPTIONS=/data/options.json

LISTEN_ADDR=$(jq -r '.listen_address' "$OPTIONS")
LISTEN_PORT=$(jq -r '.listen_port' "$OPTIONS")
SERVERS=$(jq -r '.server_names | join("\\', \\'")' "$OPTIONS")
RELAYS=$(jq -r '.relays | join("\\', \\'")' "$OPTIONS")

cat > "$CONF" <<EOF
server_names = ['${SERVERS}']
listen_addresses = ['${LISTEN_ADDR}:${LISTEN_PORT}']

require_dnssec = true
require_nolog = true
require_nofilter = true

[anonymized_dns]
routes = [
  { server_name='$(jq -r '.server_names[0]' "$OPTIONS")', via=['${RELAYS}'] }
]
EOF

echo "[INFO] Starting dnscrypt-proxy..."
exec /usr/local/bin/dnscrypt-proxy -config "$CONF"