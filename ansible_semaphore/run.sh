#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

# Read options from Home Assistant
ADMIN_LOGIN=$(jq -r '.admin_login // "admin"' $CONFIG_PATH)
ADMIN_PASSWORD=$(jq -r '.admin_password // "changeme"' $CONFIG_PATH)
CONFIG_DIR=$(jq -r '.config_path // "/share/ansible_semaphore"' $CONFIG_PATH)
SCHEDULE_TZ=$(jq -r '.schedule_timezone // "Africa/Johannesburg"' $CONFIG_PATH)
DB_DIALECT=$(jq -r '.db_dialect // "bolt"' $CONFIG_PATH)

mkdir -p "$CONFIG_DIR"

SEMAPHORE_CONFIG="$CONFIG_DIR/config.json"
DB_FILE="$CONFIG_DIR/database.boltdb"

# Apply timezone for Semaphore schedules
export SEMAPHORE_SCHEDULE_TIMEZONE="$SCHEDULE_TZ"

# Generate a config.json if not present
if [ ! -f "$SEMAPHORE_CONFIG" ]; then
    echo "Generating Semaphore config at $SEMAPHORE_CONFIG..."
    if [ "$DB_DIALECT" = "bolt" ]; then
        cat > "$SEMAPHORE_CONFIG" <<EOF
{
  "dialect": "bolt",
  "bolt": { "host": "$DB_FILE" },
  "tmp_path": "/tmp/semaphore",
  "port": "8055",
  "schedule": { "timezone": "$SCHEDULE_TZ" }
}
EOF
    else
        cat > "$SEMAPHORE_CONFIG" <<EOF
{
  "dialect": "$DB_DIALECT",
  "tmp_path": "/tmp/semaphore",
  "port": "8055",
  "schedule": { "timezone": "$SCHEDULE_TZ" }
}
EOF
    fi
fi

# Initialize DB only for bolt
if [ "$DB_DIALECT" = "bolt" ] && [ ! -f "$DB_FILE" ]; then
    echo "Initializing Semaphore with admin account (BoltDB)..."
    /usr/local/bin/semaphore user add \
        --admin \
        --login "$ADMIN_LOGIN" \
        --name "Admin" \
        --email "admin@example.com" \
        --password "$ADMIN_PASSWORD" \
        --config "$SEMAPHORE_CONFIG"
fi

# Start Semaphore with generated config
exec /usr/local/bin/semaphore -config "$SEMAPHORE_CONFIG"
