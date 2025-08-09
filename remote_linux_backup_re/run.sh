#!/bin/bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
APP_CFG="/config/remote_linux_backup.json"

mkdir -p /backup /mnt

# Update OS packages (non-fatal if offline)
if command -v apt-get >/dev/null 2>&1; then
  {
    echo "[INFO] Updating container OS packages..."
    apt-get update && apt-get upgrade -y
    apt-get clean && rm -rf /var/lib/apt/lists/*
  } || echo "[WARN] OS update skipped (likely offline). Continuing startup..."
fi

# Ensure persistent app config
if [ ! -f "$APP_CFG" ]; then
  cat > "$APP_CFG" <<'JSON'
{
  "known_hosts": [],
  "servers": [],
  "server_presets": [],
  "jobs": [],
  "mounts": [],
  "gotify_enabled": false,
  "gotify_url": "",
  "gotify_token": "",
  "dropbox_enabled": false,
  "dropbox_remote": "dropbox:HA-Backups"
}
JSON
fi

# Ensure options.json fallback (Supervisor usually writes this)
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

# Read UI port
UI_PORT=$(jq -r '.ui_port // 8066' "$CONFIG_PATH" 2>/dev/null || echo 8066)

# Auto-mount presets from APP_CFG
if jq -e '.mounts | length > 0' "$APP_CFG" >/dev/null 2>&1; then
  mapfile -t MOUNTS < <(jq -c '.mounts[] | select(.auto_mount==true)' "$APP_CFG")
  for m in "${MOUNTS[@]}"; do
    proto=$(jq -r '.proto // ""' <<<"$m")
    server=$(jq -r '.server // ""' <<<"$m")
    share=$(jq -r '.share // ""' <<<"$m")
    mountp=$(jq -r '.mount // ""' <<<"$m")
    user=$(jq -r '.username // ""' <<<"$m")
    pass=$(jq -r '.password // ""' <<<"$m")
    opts_extra=$(jq -r '.options // ""' <<<"$m")

    [ -z "$proto" ] || [ -z "$server" ] || [ -z "$share" ] || [ -z "$mountp" ] && continue
    mkdir -p "$mountp"
    if ! mountpoint -q "$mountp"; then
      if [[ "$proto" == "cifs" || "$proto" == "smb" ]]; then
        mopts="rw,vers=3.1.1,iocharset=utf8"
        [ -n "$user" ] && mopts="$mopts,username=$user"
        [ -n "$pass" ] && mopts="$mopts,password=$pass"
        [ -n "$opts_extra" ] && mopts="$mopts,$opts_extra"
        echo "[INFO] Auto-mount CIFS //$server/$share -> $mountp (opts: $mopts)"
        mount -t cifs "//$server/$share" "$mountp" -o "$mopts" || echo "[WARN] CIFS auto-mount failed for $mountp"
      elif [ "$proto" = "nfs" ]; then
        mopts="${opts_extra:-rw}"
        echo "[INFO] Auto-mount NFS $server:$share -> $mountp (opts: $mopts)"
        mount -t nfs "$server:$share" "$mountp" -o "$mopts" || echo "[WARN] NFS auto-mount failed for $mountp"
      fi
    fi
  done
fi

# Scheduler & cron (non-fatal)
python3 /app/scheduler.py apply || true
service cron start || true

# API
cd /app
exec gunicorn -w 2 --threads 4 -b 0.0.0.0:"$UI_PORT" api:app
