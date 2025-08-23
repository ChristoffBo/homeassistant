#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

# Read options from Home Assistant
ADMIN_LOGIN=$(jq -r '.admin_login // "admin"' $CONFIG_PATH)
ADMIN_PASSWORD=$(jq -r '.admin_password // "changeme"' $CONFIG_PATH)
CONFIG_DIR=$(jq -r '.config_path // "/share/ansible_semaphore"' $CONFIG_PATH)
SCHEDULE_TZ=$(jq -r '.schedule_timezone // "Africa/Johannesburg"' $CONFIG_PATH)

mkdir -p "$CONFIG_DIR"

# Apply timezone for Semaphore schedules
export SEMAPHORE_SCHEDULE_TIMEZONE="$SCHEDULE_TZ"

# Initialize Semaphore DB if not present
if [ ! -f "$CONFIG_DIR/database.boltdb" ]; then
    echo "Initializing Semaphore with admin account..."
    /usr/local/bin/semaphore user add \
        --admin \
        --login "$ADMIN_LOGIN" \
        --name "Admin" \
        --email "admin@example.com" \
        --password "$ADMIN_PASSWORD"
fi

# Start with persistent config dir
exec /usr/local/bin/semaphore -config "$CONFIG_DIR"
