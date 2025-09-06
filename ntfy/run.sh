#!/usr/bin/env bash
set -euo pipefail

OPTS_FILE="/data/options.json"
mkdir -p /data /data/ntfy || true

# -------- find ntfy binary --------
resolve_ntfy() {
  for p in "$(command -v ntfy 2>/dev/null || true)" /usr/bin/ntfy /bin/ntfy /usr/local/bin/ntfy /app/ntfy; do
    if [ -n "${p:-}" ] && [ -x "$p" ]; then
      echo "$p"; return 0
    fi
  done
  if command -v find >/dev/null 2>&1; then
    found="$(find / -maxdepth 3 -type f -name ntfy -perm -111 2>/dev/null | head -n 1 || true)"
    if [ -n "${found:-}" ]; then
      echo "$found"; return 0
    fi
  fi
  echo "ERROR: ntfy binary not found" >&2
  exit 127
}
NTFY_BIN="$(resolve_ntfy)"

# -------- read options --------
jqbin="$(command -v jq || true)"
if [ -z "$jqbin" ] || [ ! -f "$OPTS_FILE" ]; then
  echo "[ntfy-addon] WARNING: jq/options.json not available; using defaults"
  listen_port=8008
  base_url=""
  behind_proxy=true
  att_enabled=true
  att_dir="/data/attachments"
  att_file_size="15M"
  att_total_size="5G"
  att_expiry="3h"
  cache_file="/data/cache.db"
  auth_enabled=false
  auth_default="read-write"
  admin_user=""
  admin_pass=""
else
  listen_port=$(jq -r '.listen_port // 8008' "$OPTS_FILE")
  base_url=$(jq -r '.base_url // ""' "$OPTS_FILE")
  behind_proxy=$(jq -r '.behind_proxy // true' "$OPTS_FILE")
  att_enabled=$(jq -r '.attachments.enabled // true' "$OPTS_FILE")
  att_dir=$(jq -r '.attachments.dir // "/data/attachments"' "$OPTS_FILE")
  att_file_size=$(jq -r '.attachments.file_size_limit // "15M"' "$OPTS_FILE")
  att_total_size=$(jq -r '.attachments.total_size_limit // "5G"' "$OPTS_FILE")
  att_expiry=$(jq -r '.attachments.expiry // "3h"' "$OPTS_FILE")
  cache_file=$(jq -r '.cache.file // "/data/cache.db"' "$OPTS_FILE")
  auth_enabled=$(jq -r '.auth.enabled // false' "$OPTS_FILE")
  auth_default=$(jq -r '.auth.default_access // "read-write"' "$OPTS_FILE")
  admin_user=$(jq -r '.auth.admin_user // ""' "$OPTS_FILE")
  admin_pass=$(jq -r '.auth.admin_password // ""' "$OPTS_FILE")
fi

# -------- defaults --------
if [ -z "${base_url}" ] || [ "${base_url}" = "null" ]; then
  base_url="http://127.0.0.1:${listen_port}"
  echo "[ntfy-addon] INFO: base_url not set; defaulting to ${base_url}"
fi

mkdir -p "$(dirname "$cache_file")" "$att_dir"

# -------- build YAML config --------
cfg="/data/server.yml"
cat > "$cfg" <<EOF
listen-http: 0.0.0.0:${listen_port}
behind-proxy: ${behind_proxy}
base-url: ${base_url}
cache-file: ${cache_file}
EOF

if [ "${att_enabled}" = "true" ]; then
cat >> "$cfg" <<EOF
attachment-cache-dir: ${att_dir}
attachment-file-size-limit: ${att_file_size}
attachment-total-size-limit: ${att_total_size}
attachment-expiry-duration: ${att_expiry}
EOF
fi

if [ "${auth_enabled}" = "true" ]; then
cat >> "$cfg" <<EOF
auth-file: /data/user.db
auth-default-access: ${auth_default}
EOF
  if [ -n "${admin_user}" ] && [ -n "${admin_pass}" ]; then
    hashed="$("$NTFY_BIN" user hash "$admin_pass" | tr -d '\r')"
    cat >> "$cfg" <<EOF
auth-users:
  - ${admin_user}:${hashed}:admin
EOF
  fi
fi

echo "[ntfy-addon] ------- /data/server.yml -------"
cat "$cfg"
echo "[ntfy-addon] --------------------------------"

echo "[ntfy-addon] Using ntfy binary: $NTFY_BIN"
echo "[ntfy-addon] Starting ntfy with /data/server.yml on port ${listen_port}"
exec "$NTFY_BIN" serve --config "$cfg"
