#!/usr/bin/env bash
set -euo pipefail

OPTS_FILE="/data/options.json"
mkdir -p /data /data/ntfy || true

# --- find ntfy binary ---
resolve_ntfy() {
  for p in "$(command -v ntfy 2>/dev/null || true)" /usr/bin/ntfy /bin/ntfy /usr/local/bin/ntfy /app/ntfy; do
    if [ -n "${p:-}" ] && [ -x "$p" ]; then
      echo "$p"; return 0
    fi
  done
  echo "ERROR: ntfy binary not found" >&2
  exit 127
}
NTFY_BIN="$(resolve_ntfy)"

# --- read options with defaults ---
read_opts() {
  if command -v jq >/dev/null 2>&1 && [ -f "$OPTS_FILE" ]; then
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
  else
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
  fi
}
read_opts

# --- normalize booleans to true/false ---
norm_bool() { case "${1,,}" in 1|true|yes|on) echo true;; *) echo false;; esac; }
bp_bool="$(norm_bool "${behind_proxy}")"
att_bool="$(norm_bool "${att_enabled}")"
auth_bool="$(norm_bool "${auth_enabled}")"

# --- sanitize/default base_url (no path allowed) ---
if [ -z "${base_url:-}" ] || [ "${base_url}" = "null" ]; then
  base_url="http://127.0.0.1:${listen_port}"
  echo "[ntfy-addon] INFO: base_url not set; defaulting to ${base_url}"
fi
orig_base="${base_url}"
# strip any path/query (# keep only scheme://host[:port])
base_url="$(printf '%s' "${base_url}" | sed -E 's#^(https?://[^/]+).*#\1#')"
if [ "${orig_base}" != "${base_url}" ]; then
  echo "[ntfy-addon] WARNING: base_url had a path; sanitized to '${base_url}' (ntfy forbids sub-paths)."
fi

# --- ensure dirs ---
mkdir -p "$(dirname "$cache_file")" "$att_dir"

# --- write YAML cleanly ---
cfg="/data/server.yml"
# use printf to avoid accidental double quotes
{
  printf 'listen-http: "0.0.0.0:%s"\n' "${listen_port}"
  printf 'behind-proxy: %s\n' "${bp_bool}"
  printf 'base-url: "%s"\n' "${base_url}"
  printf 'cache-file: "%s"\n' "${cache_file}"

  if [ "${att_bool}" = "true" ]; then
    printf 'attachment-cache-dir: "%s"\n' "${att_dir}"
    printf 'attachment-file-size-limit: "%s"\n' "${att_file_size}"
    printf 'attachment-total-size-limit: "%s"\n' "${att_total_size}"
    printf 'attachment-expiry-duration: "%s"\n' "${att_expiry}"
  fi

  if [ "${auth_bool}" = "true" ]; then
    printf 'auth-file: "/data/user.db"\n'
    printf 'auth-default-access: "%s"\n' "${auth_default}"
    if [ -n "${admin_user}" ] && [ "${admin_user}" != "null" ] && \
       [ -n "${admin_pass}" ] && [ "${admin_pass}" != "null" ]; then
      hashed="$("$NTFY_BIN" user hash "$admin_pass" | tr -d '\r')"
      printf 'auth-users:\n'
      printf '  - "%s:%s:admin"\n' "${admin_user}" "${hashed}"
    fi
  fi
} > "$cfg"

# normalize line endings & show YAML
sed -i 's/\r$//' "$cfg" || true
echo "[ntfy-addon] ------- /data/server.yml -------"
cat "$cfg" || true
echo "[ntfy-addon] --------------------------------"

echo "[ntfy-addon] Using ntfy binary: $NTFY_BIN"
echo "[ntfy-addon] Starting ntfy with /data/server.yml on port ${listen_port}"
exec "$NTFY_BIN" serve --config "$cfg"
