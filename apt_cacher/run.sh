#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH="/data/options.json"
PORT=$(jq -r '.port // 3142' "$CONFIG_PATH")

echo "[INFO] Starting apt-cacher-ng on port $PORT"

# Configure port dynamically
sed -i "s/^Port: .*/Port: $PORT/" /etc/apt-cacher-ng/acng.conf

# Create cache directory if missing
mkdir -p /var/cache/apt-cacher-ng
chown -R apt-cacher-ng:apt-cacher-ng /var/cache/apt-cacher-ng

# Start apt-cacher-ng
exec /usr/sbin/apt-cacher-ng -c /etc/apt-cacher-ng
