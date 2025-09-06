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
  echo "ERROR: ntfy binary not found in PATH or common locations (/usr/bin/ntfy, /bin/ntfy, /usr/local/bin/ntfy, /app/ntfy), and search failed." >&2
  echo "INFO: Contents of /usr/local/bin:" >&2; ls -lah /usr/local/bin || true
  echo "INFO: Contents of /usr/bin:" >&2; ls -lah /usr/bin || true
  echo "INFO: PATH is: $PATH" >&2
  exit 127
}
NTFY_BIN="$(resolve_ntfy)"

# -------- read options (with sane defaults) --------
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

# -------- base_url defaulting (requested) --------
# If base_url is empty/null, set a safe default so ntfy accepts attachments:
# Using loopback + configured port avoids the "attachment-cache-dir requires base-url" crash.
if [ -z "${base_url:-}" ] || [ "$base_url" = "null" ]; then
  base_url="http://127.0.0.1:${listen_port}"
  echo "[ntfy-addon] INFO: base_url not set; defaulting to ${base_url}"
fi

# Ensure dirs exist
mkdir -p "$(dirname "$cache_file")" "$att_dir"

# -------- build YAML config safely --------
cfg="/data/server.yml"
{
  printf 'listen-http: "0.0.0.0:%s"\n' "${listen_port}"
  if [ "${behind_proxy}" = "true" ] || [ "${behind_proxy}" = "True" ]; then
    echo "behind-proxy: true"
  else
    echo "behind-proxy: false"
  fi
  printf 'base-url: "%s"\n' "${base_url}"
  printf 'cache-file: "%s"\n' "${cache_file}"

  if [ "${att_enabled}" = "true" ] || [ "${att_enabled}" = "True" ]; then
    printf 'attachment-cache-dir: "%s"\n' "${att_dir}"
    printf 'attachment-file-size-limit: "%s"\n' "${att_file_size}"
    printf 'attachment-total-size-limit: "%s"\n' "${att_total_size}"
    printf 'attachment-expiry-duration: "%s"\n' "${att_expiry}"
  fi

  if [ "${auth_enabled}" = "true" ] || [ "${auth_enabled}" = "True" ]; then
    echo 'auth-file: "/data/user.db"'
    printf 'auth-default-access: "%s"\n' "${auth_default}"
    if [ -n "${admin_user}" ] && [ "${admin_user}" != "null" ] && [ -n "${admin_pass}" ] && [ "${admin_pass}" != "null" ]; then
      hashed="$("$NTFY_BIN" user hash "$admin_pass" | tr -d '\r')"
      echo "auth-users:"
      printf '  - "%s:%s:admin"\n' "${admin_user}" "${hashed}"
    fi
  fi
} > "$cfg"

# quick syntax check to catch "did not find expected key"
if command -v sed >/dev/null 2>&1; then
  # ensure file ends with newline (some shells can omit)
  sed -n '$p' "$cfg" >/dev/null || true
fi

echo "[ntfy-addon] Using ntfy binary: $NTFY_BIN"
echo "[ntfy-addon] Starting ntfy with /data/server.yml on port ${listen_port}"
exec "$NTFY_BIN" serve --config "$cfg"
