#!/bin/bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
APP_CONFIG="/config/remote_linux_backup.json"
mkdir -p /backup /mnt/nas

# Make rclone read a persistent config in /config
export RCLONE_CONFIG="/config/rclone.conf"

# Ensure default HA options.json exists
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

# Ensure app config exists (UI writes here)
if [ ! -f "$APP_CONFIG" ]; then
  cat > "$APP_CONFIG" <<'JSON'
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

# Resolve UI port safely
UI_PORT="$(jq -r '.ui_port // 8066' "$CONFIG_PATH" 2>/dev/null || echo 8066)"

# Helper: mount one item
_mount_one() {
  local proto="$1" server="$2" share="$3" mountp="$4" user="$5" pass="$6" opts_extra="$7"
  mkdir -p "$mountp"
  if [ "$proto" = "cifs" ]; then
    local mopts="rw,vers=3.0,iocharset=utf8"
    [ -n "$user" ] && mopts="$mopts,username=$user"
    [ -n "$pass" ] && mopts="$mopts,password=$pass"
    [ -n "$opts_extra" ] && mopts="$mopts,$opts_extra"
    mount -t cifs "//$server/$share" "$mountp" -o "$mopts" || true
  elif [ "$proto" = "nfs" ]; then
    local mopts="${opts_extra:-rw}"
    mount -t nfs "$server:$share" "$mountp" -o "$mopts" || true
  fi
}

# Auto-mount UI-managed mounts
if jq -e '.mounts | length > 0' "$APP_CONFIG" >/dev/null 2>&1; then
  count="$(jq -r '.mounts | length' "$APP_CONFIG")"
  if [ "$count" -gt 0 ]; then
    for i in $(seq 0 $((count-1))); do
      auto="$(jq -r ".mounts[$i].auto_mount // false" "$APP_CONFIG")"
      if [ "$auto" = "true" ]; then
        proto="$(jq -r ".mounts[$i].proto" "$APP_CONFIG")"
        server="$(jq -r ".mounts[$i].server" "$APP_CONFIG")"
        share="$(jq -r ".mounts[$i].share" "$APP_CONFIG")"
        mountp="$(jq -r ".mounts[$i].mount" "$APP_CONFIG")"
        user="$(jq -r ".mounts[$i].username // \"\"" "$APP_CONFIG")"
        pass="$(jq -r ".mounts[$i].password // \"\"" "$APP_CONFIG")"
        opts="$(jq -r ".mounts[$i].options // \"\"" "$APP_CONFIG")"
        [ "$proto" = "null" ] && continue
        [ -z "$proto" ] || [ -z "$server" ] || [ -z "$share" ] || [ -z "$mountp" ] && continue
        _mount_one "$proto" "$server" "$share" "$mountp" "$user" "$pass" "$opts"
      fi
    done
  fi
fi

# Apply schedules (best-effort)
python3 /app/scheduler.py apply || true

# Start cron (BusyBox crond daemonizes by default)
if command -v crond >/dev/null 2>&1; then
  crond || true
elif command -v cron >/dev/null 2>&1; then
  service cron start || true
fi

# Start API
cd /app
exec gunicorn -w 2 -k gthread --threads 8 --timeout 120 -b "0.0.0.0:${UI_PORT}" api:app
