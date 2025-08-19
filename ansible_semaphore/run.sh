#!/bin/sh
set -e

OPTIONS_FILE="/data/options.json"

# Defaults
ADMIN_USER="admin"
ADMIN_PASS="changeme"
ADMIN_NAME="Admin"
ADMIN_EMAIL="admin@localhost"
DB_DIALECT="bolt"
TZ_SET="Etc/UTC"

if [ -f "$OPTIONS_FILE" ]; then
  ADMIN_USER=$(jq -r '.admin_user // "admin"' "$OPTIONS_FILE")
  ADMIN_PASS=$(jq -r '.admin_password // "changeme"' "$OPTIONS_FILE")
  ADMIN_NAME=$(jq -r '.admin_name // "Admin"' "$OPTIONS_FILE")
  ADMIN_EMAIL=$(jq -r '.admin_email // "admin@localhost"' "$OPTIONS_FILE")
  DB_DIALECT=$(jq -r '.db_dialect // "bolt"' "$OPTIONS_FILE")
  TZ_SET=$(jq -r '.timezone // "Etc/UTC"' "$OPTIONS_FILE")
fi

# Persist paths in /config
export SEMAPHORE_CONFIG_PATH="/config/semaphore"
export SEMAPHORE_DB_PATH="/config/semaphore-data"
export SEMAPHORE_TMP_PATH="/config/semaphore-tmp"
export SEMAPHORE_DB="/config/semaphore/semaphore.db"

mkdir -p "$SEMAPHORE_CONFIG_PATH" "$SEMAPHORE_DB_PATH" "$SEMAPHORE_TMP_PATH"

# Timezone
export TZ="$TZ_SET"
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
  ln -sf "/usr/share/zoneinfo/$TZ" /etc/localtime || true
  echo "$TZ" > /etc/timezone || true
fi

# Admin bootstrap
export SEMAPHORE_ADMIN="$ADMIN_USER"
export SEMAPHORE_ADMIN_PASSWORD="$ADMIN_PASS"
export SEMAPHORE_ADMIN_NAME="$ADMIN_NAME"
export SEMAPHORE_ADMIN_EMAIL="$ADMIN_EMAIL"

# Generate & persist cookie/encryption secrets if not present
SECRETS_FILE="$SEMAPHORE_CONFIG_PATH/secrets.env"
if [ ! -f "$SECRETS_FILE" ]; then
  COOKIE_HASH=$(head -c 32 /dev/urandom | base64)
  COOKIE_ENC=$(head -c 32 /dev/urandom | base64)
  ACCESS_KEY_ENC=$(head -c 32 /dev/urandom | base64)
  cat > "$SECRETS_FILE" <<EOF
SEMAPHORE_COOKIE_HASH=$COOKIE_HASH
SEMAPHORE_COOKIE_ENCRYPTION=$COOKIE_ENC
SEMAPHORE_ACCESS_KEY_ENCRYPTION=$ACCESS_KEY_ENC
EOF
fi
. "$SECRETS_FILE"
export SEMAPHORE_COOKIE_HASH SEMAPHORE_COOKIE_ENCRYPTION SEMAPHORE_ACCESS_KEY_ENCRYPTION

echo "[Info] Starting Semaphore UI with config in /config/semaphore"

# Hand off to Semaphore’s built-in wrapper
exec /usr/local/bin/server-wrapper