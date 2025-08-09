#!/bin/bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
mkdir -p /backup /mnt/nas /app/data

# Default options if missing
if [ ! -f "$CONFIG_PATH" ]; then
  echo '{"ui_port":8066,"gotify_enabled":false,"gotify_url":"","gotify_token":"","auto_install_tools":true,"dropbox_enabled":false,"dropbox_remote":"dropbox:HA-Backups","nas_mounts":[],"jobs":[]}' > "$CONFIG_PATH"
fi

UI_PORT=$(jq -er '.ui_port // 8066' "$CONFIG_PATH" 2>/dev/null || echo 8066)

# Mount NAS entries (schema provides list(str); each item is JSON text)
if jq -e '.nas_mounts | length >= 1' "$CONFIG_PATH" >/dev/null 2>&1; then
  while IFS= read -r row; do
    # Decode JSON string to object; if already an object, try fromjson will handle it too
    proto=$(echo "$row" | jq -r 'try fromjson | .proto // "cifs"')
    server=$(echo "$row" | jq -r 'try fromjson | .server // empty')
    share=$(echo "$row" | jq -r 'try fromjson | .share // empty')
    mountp=$(echo "$row" | jq -r 'try fromjson | .mount // "/mnt/nas"')
    user=$(echo "$row" | jq -r 'try fromjson | .username // empty')
    pass=$(echo "$row" | jq -r 'try fromjson | .password // empty')

    [ -z "$server" ] && { echo "WARN: NAS mount missing server; skipping"; continue; }
    [ -z "$share" ] && { echo "WARN: NAS mount missing share; skipping"; continue; }

    mkdir -p "$mountp"
    if [ "$proto" = "cifs" ]; then
      opts="rw,iocharset=utf8,file_mode=0777,dir_mode=0777,vers=3.0"
      [ -n "$user" ] && opts="$opts,username=$user"
      [ -n "$pass" ] && opts="$opts,password=$pass"
      if ! mount -t cifs "//$server/$share" "$mountp" -o "$opts"; then
        echo "WARN: CIFS mount failed for //$server/$share -> $mountp"
      fi
    else
      if ! mount -t nfs "$server:$share" "$mountp"; then
        echo "WARN: NFS mount failed for $server:$share -> $mountp"
      fi
    fi
  done < <(jq -cr '.nas_mounts[]' "$CONFIG_PATH")
fi

# Dropbox rclone config
DROPBOX_ENABLED=$(jq -er '.dropbox_enabled // false' "$CONFIG_PATH" 2>/dev/null || echo false)
if [ "$DROPBOX_ENABLED" = "true" ]; then
  mkdir -p /root/.config/rclone
  if [ -f /config/rclone.conf ]; then
    cp /config/rclone.conf /root/.config/rclone/rclone.conf
  elif [ ! -f /root/.config/rclone/rclone.conf ]; then
    printf "# Configure Dropbox remote here or upload /config/rclone.conf\n" > /root/.config/rclone/rclone.conf
  fi
fi

# Copy options and apply schedules
cp "$CONFIG_PATH" /app/data/options.json || true
python3 /app/scheduler.py apply || true
service cron start

# Launch API
cd /app
exec gunicorn -w 2 -b 0.0.0.0:"$UI_PORT" api:app