#!/usr/bin/env bash
set -euo pipefail

OPTIONS=/data/options.json
CONF=/config/dnscrypt-proxy.toml

LISTEN_ADDR=$(jq -r '.listen_address' "$OPTIONS")
LISTEN_PORT=$(jq -r '.listen_port' "$OPTIONS")

SERVERS_JSON=$(jq -c '.server_names' "$OPTIONS")
RELAYS_JSON=$(jq -c '.relays' "$OPTIONS")
SERVER0=$(jq -r '.server_names[0]' "$OPTIONS")

REQUIRE_DNSSEC=$(jq -r '.require_dnssec' "$OPTIONS")
REQUIRE_NOLOG=$(jq -r '.require_nolog' "$OPTIONS")
REQUIRE_NOFILTER=$(jq -r '.require_nofilter' "$OPTIONS")
CACHE=$(jq -r '.cache' "$OPTIONS")
CACHE_SIZE=$(jq -r '.cache_size' "$OPTIONS")
CACHE_MIN_TTL=$(jq -r '.cache_min_ttl' "$OPTIONS")
CACHE_MAX_TTL=$(jq -r '.cache_max_ttl' "$OPTIONS")
TIMEOUT_MS=$(jq -r '.timeout_ms' "$OPTIONS")
KEEPALIVE=$(jq -r '.keepalive_sec' "$OPTIONS")
BOOTSTRAP_JSON=$(jq -c '.bootstrap_resolvers' "$OPTIONS")
LOG_LEVEL=$(jq -r '.log_level' "$OPTIONS")
MAX_CLIENTS=$(jq -r '.max_clients // 250' "$OPTIONS")

mkdir -p /config

cat > "$CONF" <<EOF
# Listener
listen_addresses = ["${LISTEN_ADDR}:${LISTEN_PORT}"]
max_clients = ${MAX_CLIENTS}

# Resolver selection
server_names = ${SERVERS_JSON}

# Policies
require_dnssec   = ${REQUIRE_DNSSEC}
require_nolog    = ${REQUIRE_NOLOG}
require_nofilter = ${REQUIRE_NOFILTER}

# Performance
cache = ${CACHE}
cache_size = ${CACHE_SIZE}
cache_min_ttl = ${CACHE_MIN_TTL}
cache_max_ttl = ${CACHE_MAX_TTL}
timeout = ${TIMEOUT_MS}
keepalive = ${KEEPALIVE}

# Bootstrap for DoH hostnames & lists
bootstrap_resolvers = ${BOOTSTRAP_JSON}
log_level = ${LOG_LEVEL}

# Sources (canonical)
[sources]

  [sources.public-resolvers]
  urls = [
    "https://download.dnscrypt.info/resolvers-list/v3/public-resolvers.md"
  ]
  cache_file = "/config/public-resolvers.md"
  minisign_key = "RWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3"
  refresh_delay = 72
  prefix = ""

  [sources.relays]
  urls = [
    "https://download.dnscrypt.info/resolvers-list/v3/relays.md"
  ]
  cache_file = "/config/relays.md"
  minisign_key = "RWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3"
  refresh_delay = 72
  prefix = ""

# Anonymized DNS
[anonymized_dns]
skip_incompatible = true
routes = [
  { server_name = "${SERVER0}", via = ${RELAYS_JSON} }
]
EOF

echo "[INFO] Generated $CONF"
echo "[INFO] Starting dnscrypt-proxy ..."
exec /usr/local/bin/dnscrypt-proxy -config "$CONF" -loglevel "$LOG_LEVEL"