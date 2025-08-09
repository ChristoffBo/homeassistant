#!/bin/bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
APP_CFG="/config/remote_linux_backup.json"
mkdir -p /backup /mnt

# Ensure app config exists
if [ ! -f "$APP_CFG" ]; then
  cat > "$APP_CFG" <<'JSON'
{
  "known_hosts": [],
  "server_presets": [],
  "jobs": [],
  "nas_mounts": [],
  "gotify_enabled": false,
  "gotify_url": "",
  "gotify_token": "",
  "dropbox_enabled": false,
  "dropbox_remote": "dropbox:HA-Backups",
  "mounts": [],
  "servers": []
}
JSON
fi

# Ensure HA options default exists (read-only at runtime)
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

UI_PORT=$(jq -r '.ui_port // 8066' "$CONFIG_PATH" 2>/dev/null || echo 8066)

# Auto-mount presets marked auto_mount: true
if jq -e '.mounts | length > 0' "$APP_CFG" >/dev/null 2>&1; then
  mapfile -t MOUNTS < <(jq -c '.mounts[] | select(.auto_mount==true)' "$APP_CFG")
  for m in "${MOUNTS[@]}"; do
    proto=$(jq -r '.proto' <<<"$m"); server=$(jq -r '.server' <<<"$m")
    share=$(jq -r '.share' <<<"$m"); mountp=$(jq -r '.mount' <<<"$m")
    user=$(jq -r '.username' <<<"$m"); pass=$(jq -r '.password' <<<"$m")
    opts_extra=$(jq -r '.options' <<<"$m")
    [ -z "$proto" ] && continue
    mkdir -p "$mountp"
    if ! mountpoint -q "$mountp"; then
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
    fi
  done
fi

# Apply schedules & start cron (foreground, syslog)
python3 /app/scheduler.py apply || true
crond -n -s -L /var/log/remote_linux_backup.log &

# Start API
cd /app
exec gunicorn -w 2 -b 0.0.0.0:"$UI_PORT" api:app
