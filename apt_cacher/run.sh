#!/bin/bash
set -e

CONFIG_PATH="/data/options.json"
DEFAULT_PORT=3142

# Parse port manually without jq
if [[ -f "$CONFIG_PATH" ]]; then
  PORT=$(grep -oP '"port"\s*:\s*\K[0-9]+' "$CONFIG_PATH" || echo "")
else
  PORT=""
fi

# Fallback to default if parsing fails
if [[ -z "$PORT" ]]; then
  PORT=$DEFAULT_PORT
fi

echo "[INFO] Starting apt-cacher-ng on port $PORT"

# Update config file
sed -i "s/^Port: .*/Port: $PORT/" /etc/apt-cacher-ng/acng.conf

# Ensure cache dir exists
mkdir -p /var/cache/apt-cacher-ng
chown -R apt-cacher-ng:apt-cacher-ng /var/cache/apt-cacher-ng

# Start apt-cacher-ng
exec /usr/sbin/apt-cacher-ng -c /etc/apt-cacher-ng
