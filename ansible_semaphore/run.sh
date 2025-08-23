#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

# Read options from Home Assistant
ADMIN_LOGIN=$(jq -r '.admin_login // "admin"' $CONFIG_PATH)
ADMIN_PASSWORD=$(jq -r '.admin_password // "changeme"' $CONFIG_PATH)
CONFIG_DIR=$(jq -r '.config_path // "/share/ansible_semaphore"' $CONFIG_PATH)
SCHEDULE_TZ=$(jq -r '.schedule_timezone // "Africa/Johannesburg"' $CONFIG_PATH)

mkdir -p "$CONFIG_DIR"

SEMAPHORE_CONFIG="$CONFIG_DIR/config.json"
DB_FILE="$CONFIG_DIR/database.boltdb"

# Force timezone for schedules
export SEMAPHORE_SCHEDULE_TIMEZONE="$SCHEDULE_TZ"

# Always generate a proper BoltDB config if missing
if [ ! -f "$SEMAPHORE_CONFIG" ]; then
    echo "Generating Semaphore config at $SEMAPHORE_CONFIG..."
    cat > "$SEMAPHORE_CONFIG" <<EOF
{
  "dialect": "bolt",
  "bolt": { "file": "$DB_FILE" },
  "tmp_path": "/tmp/semaphore",
  "port": "8055",
  "cookie_hash": "changeme-cookie-hash",
  "cookie_encryption": "changeme-cookie-key",
  "access_key_encryption": "changeme-access-key",
  "schedule": { "timezone": "$SCHEDULE_TZ" }
}
EOF
fi

# Make sure DB folder exists
mkdir -p "$(dirname "$DB_FILE")"

# Ensure admin exists (create only if DB is new)
if [ ! -f "$DB_FILE" ]; then
    echo "Initializing Semaphore admin user..."
    /usr/local/bin/semaphore user add \
        --admin \
        --login "$ADMIN_LOGIN" \
        --name "Admin" \
        --email "admin@example.com" \
        --password "$ADMIN_PASSWORD" \
        --config "$SEMAPHORE_CONFIG"
fi

# Start Semaphore server with BoltDB config
exec /usr/local/bin/semaphore server --config "$SEMAPHORE_CONFIG"
