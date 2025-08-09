#!/bin/bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
mkdir -p /backup /mnt/nas

# Ensure default options file exists for first start
if [ ! -f "$CONFIG_PATH" ]; then
  cat > "$CONFIG_PATH" <<'JSON'
{
  "known_hosts": [],
  "ui_port": 8066,
  "gotify_enabled": false,
  "gotify_url": "",
  "gotify_token": "",
  "auto_install_tools": true,
  "dropbox_enabled": false,
  "dropbox_remote": "dropbox:HA-Backups",
  "nas_mounts": [],
  "server_presets": [],
  "jobs": []
}
JSON
fi

# NEW: auto-install tools if requested
if jq -e '.auto_install_tools == true' "$CONFIG_PATH" >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      cifs-utils nfs-common jq curl python3-pip cron || true
  fi
fi

# Resolve UI port safely
UI_PORT="$(jq -r '.ui_port // 8066' "$CONFIG_PATH" 2>/dev/null || echo 8066)"

# Mount NAS entries (proto=cifs|nfs;server=...;share=...;mount=/mnt/nas/name;username=...;password=...;options=...)
if jq -e '.nas_mounts | length > 0' "$CONFIG_PATH" >/dev/null 2>&1; then
  mapfile -t NAS_ITEMS < <(jq -r '.nas_mounts[]' "$CONFIG_PATH")
  for row in "${NAS_ITEMS[@]}"; do
    declare -A kv; kv=()
    IFS=';' read -ra parts <<< "$row"
    for p in "${parts[@]}"; do
      k="${p%%=*}"; v="${p#*=}"
      k="$(echo "$k" | xargs)"; v="$(echo "$v" | xargs)"
      [ -n "$k" ] && kv["$k"]="$v"
    done
    proto="${kv[proto]:-}"; server="${kv[server]:-}"; share="${kv[share]:-}"; mountp="${kv[mount]:-}"
    user="${kv[username]:-}"; pass="${kv[password]:-}"; opts_extra="${kv[options]:-}"
    if [ -z "${proto}" ] || [ -z "${server}" ] || [ -z "${share}" ] || [ -z "${mountp}" ]; then
      continue
    fi
    mkdir -p "$mountp"
    if [ "$proto" = "cifs" ]; then
      mopts="rw,vers=3.0,iocharset=utf8"
      [ -n "$user" ] && mopts="$mopts,username=$user"
      [ -n "$pass" ] && mopts="$mopts,password=$pass"
      [ -n "$opts_extra" ] && mopts="$mopts,$opts_extra"
      mount -t cifs "//$server/$share" "$mountp" -o "$mopts" || true
    elif [ "$proto" = "nfs" ]; then
      mopts="${opts_extra:-rw}"
      mount -t nfs "$server:$share" "$mountp" -o "$mopts" || true
    fi
  done
fi

# Apply schedules (best-effort)
python3 /app/scheduler.py apply || true

# Start cron reliably (Debian or BusyBox)
if command -v crond >/dev/null 2>&1; then
  crond -b -l 8 || true
elif command -v cron >/dev/null 2>&1; then
  service cron start || true
fi

# FIXED: start API with safe defaults
cd /app
exec gunicorn -w 2 -k gthread --threads 8 --timeout 120 -b "0.0.0.0:${UI_PORT}" api:app
