#!/bin/bash
set -e

CONFIG_PATH="/data/options.json"
PORT=$(jq -r '.port // 3142' "$CONFIG_PATH")

echo "[INFO] Starting apt-cacher-ng on port $PORT"

# Update port in config
sed -i "s/^Port: .*/Port: $PORT/" /etc/apt-cacher-ng/acng.conf

# Ensure cache directory exists
mkdir -p /var/cache/apt-cacher-ng
chown -R apt-cacher-ng:apt-cacher-ng /var/cache/apt-cacher-ng

# Start service
exec /usr/sbin/apt-cacher-ng -c /etc/apt-cacher-ng
