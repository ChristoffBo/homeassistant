#!/usr/bin/env bash
set -euo pipefail

OPTS_FILE="/data/options.json"
mkdir -p /data /data/ntfy || true

# ---------- find ntfy binary ----------
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

# ---------- read options (with defaults) ----------
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

# ---------- normalize booleans ----------
norm_bool() { case "${1,,}" in 1|true|yes|on) echo true;; *) echo false;; esac; }
bp_bool="$(norm_bool "${behind_proxy}")"
att_bool="$(norm_bool "${att_enabled}")"
auth_bool="$(norm_bool "${auth_enabled}")"

# ---------- sanitize/default base_url (MUST be origin; no path allowed) ----------
if [ -z "${base_url:-}" ] || [ "${base_url}" = "null" ]; then
  base_url="http://127.0.0.1:${listen_port}"
  echo "[ntfy-addon] INFO: base_url not set; defaulting to ${base_url}"
fi
orig_base="${base_url}"
# strip any path/query/fragment: keep only scheme://host[:port]
base_url="$(printf '%s' "${base_url}" | sed -E 's#^(https?://[^/]+).*#\1#')"
if [ "${orig_base}" != "${base_url}" ]; then
  echo "[ntfy-addon] WARNING: base_url contained a path; sanitized to '${base_url}'. ntfy forbids sub-paths."
fi

# ---------- ensure dirs ----------
mkdir -p "$(dirname "$cache_file")" "$att_dir"

# ---------- build ntfy CLI args (no YAML) ----------
args=( serve )
args+=( --listen-http "0.0.0.0:${listen_port}" )
args+=( --cache-file "${cache_file}" )
args+=( --base-url "${base_url}" )
if [ "${bp_bool}" = "true" ]; then
  args+=( --behind-proxy )
fi

# attachments require base-url; we have one sanitized above
if [ "${att_bool}" = "true" ]; then
  args+=( --attachment-cache-dir "${att_dir}" )
  args+=( --attachment-file-size-limit "${att_file_size}" )
  args+=( --attachment-total-size-limit "${att_total_size}" )
  args+=( --attachment-expiry-duration "${att_expiry}" )
fi

# auth: create auth file if enabled; add admin if provided
if [ "${auth_bool}" = "true" ]; then
  auth_file="/data/user.db"
  : > "${auth_file}"
  if [ -n "${admin_user}" ] && [ "${admin_user}" != "null" ] && \
     [ -n "${admin_pass}" ] && [ "${admin_pass}" != "null" ]; then
    hashed="$("$NTFY_BIN" user hash "$admin_pass" | tr -d '\r')"
    printf '%s:%s:admin\n' "${admin_user}" "${hashed}" >> "${auth_file}"
    echo "[ntfy-addon] INFO: created admin user '${admin_user}' in ${auth_file}"
  fi
  args+=( --auth-file "${auth_file}" )
  args+=( --auth-default-access "${auth_default}" )
fi

# ---------- show final command for debugging ----------
echo "[ntfy-addon] Using ntfy binary: ${NTFY_BIN}"
echo "[ntfy-addon] Exec: ${NTFY_BIN} ${args[*]}"

# ---------- launch ----------
exec "${NTFY_BIN}" "${args[@]}"
