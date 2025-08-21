#!/usr/bin/env bash
set -euo pipefail

OPTIONS=/data/options.json
CONF=/config/dnscrypt-proxy.toml

# Read options from Supervisor
LISTEN_ADDR=$(jq -r '.listen_address' "$OPTIONS")
LISTEN_PORT=$(jq -r '.listen_port' "$OPTIONS")

# Use raw JSON to avoid shell-quoting issues; TOML accepts JSON-style arrays.
SERVERS_JSON=$(jq -c '.server_names' "$OPTIONS")      # e.g. ["quad9-doh-ip4-port443","cloudflare","cisco"]
RELAYS_JSON=$(jq -c '.relays' "$OPTIONS")             # e.g. ["anon-cs-de","anon-cs-fr","anon-scaleway-nl"]
SERVER0=$(jq -r '.server_names[0]' "$OPTIONS")        # e.g. quad9-doh-ip4-port443

REQUIRE_DNSSEC=$(jq -r '.require_dnssec' "$OPTIONS")
REQUIRE_NOLOG=$(jq -r '.require_nolog' "$OPTIONS")
REQUIRE_NOFILTER=$(jq -r '.require_nofilter' "$OPTIONS")
CACHE=$(jq -r '.cache' "$OPTIONS")
CACHE_SIZE=$(jq -r '.cache_size' "$OPTIONS")
CACHE_MIN_TTL=$(jq -r '.cache_min_ttl' "$OPTIONS")
CACHE_MAX_TTL=$(jq -r '.cache_max_ttl' "$OPTIONS")
TIMEOUT_MS=$(jq -r '.timeout_ms' "$OPTIONS")
KEEPALIVE=$(jq -r '.keepalive_sec' "$OPTIONS")
FALLBACK=$(jq -r '.fallback_resolver' "$OPTIONS")
LOG_LEVEL=$(jq -r '.log_level' "$OPTIONS")

mkdir -p /config

cat > "$CONF" <<EOF
server_names = ${SERVERS_JSON}
listen_addresses = ["${LISTEN_ADDR}:${LISTEN_PORT}"]

require_dnssec   = ${REQUIRE_DNSSEC}
require_nolog    = ${REQUIRE_NOLOG}
require_nofilter = ${REQUIRE_NOFILTER}

cache = ${CACHE}
cache_size = ${CACHE_SIZE}
cache_min_ttl = ${CACHE_MIN_TTL}
cache_max_ttl = ${CACHE_MAX_TTL}

timeout = ${TIMEOUT_MS}
keepalive = ${KEEPALIVE}

fallback_resolver = "${FALLBACK}"
log_level = ${LOG_LEVEL}

[anonymized_dns]
routes = [
  { server_name = "${SERVER0}", via = ${RELAYS_JSON} }
]
EOF

echo "[INFO] Generated $CONF"
echo "[INFO] Starting dnscrypt-proxy ..."
exec /usr/local/bin/dnscrypt-proxy -config "$CONF" -loglevel "$LOG_LEVEL"