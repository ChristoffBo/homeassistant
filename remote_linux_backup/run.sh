#!/bin/bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
mkdir -p /backup /mnt/nas

# Default options if missing
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

UI_PORT=$(jq -er '.ui_port // 8066' "$CONFIG_PATH" 2>/dev/null || echo 8066)

# Mount NAS entries (each item is "proto=cifs;server=...;share=...;mount=/mnt/nas/name;username=...;password=...;options=...")
if jq -e '.nas_mounts | length >= 1' "$CONFIG_PATH" >/dev/null 2>&1; then
  mapfile -t NAS_ITEMS < <(jq -r '.nas_mounts[]' "$CONFIG_PATH")
  for row in "${NAS_ITEMS[@]}"; do
    # parse key=value;key=value
    declare -A kv; kv=()
    IFS=';' read -ra parts <<< "$row"
    for p in "${parts[@]}"; do
      k="${p%%=*}"; v="${p#*=}"
      k="$(echo "$k" | xargs)"; v="$(echo "$v" | xargs)"
      [ -n "$k" ] && kv["$k"]="$v"
    done
    proto="${kv[proto]:-}"
    server="${kv[server]:-}"
    share="${kv[share]:-}"
    mountp="${kv[mount]:-}"
    user="${kv[username]:-}"
    pass="${kv[password]:-}"
    opts_extra="${kv[options]:-}"
    [ -z "$proto" ] || [ -z "$server" ] || [ -z "$share" ] || [ -z "$mountp" ] && continue
    mkdir -p "$mountp"
    if [ "$proto" = "cifs" ]; then
      # Build CIFS options
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

# Dropbox rclone config helper
if jq -e '.dropbox_enabled == true' "$CONFIG_PATH" >/dev/null 2>&1; then
  mkdir -p /root/.config/rclone
  if [ -f /config/rclone.conf ]; then
    cp /config/rclone.conf /root/.config/rclone/rclone.conf
  elif [ ! -f /root/.config/rclone/rclone.conf ]; then
    printf "# Configure Dropbox remote here or upload /config/rclone.conf\n" > /root/.config/rclone/rclone.conf
  fi
fi

# Apply schedules
python3 /app/scheduler.py apply || true
service cron start || true

# Launch API
cd /app
exec gunicorn -w 2 -b 0.0.0.0:"$UI_PORT" api:app
