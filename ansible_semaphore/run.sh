#!/usr/bin/env bash
set -euo pipefail

# Persistent base inside Supervisor-managed storage
BASE="/data/semaphore"
ETC="$BASE/etc"
LIB="$BASE/lib"
TMP="$BASE/tmp"
PLAY="$BASE/playbooks"

# Create persistent dirs
mkdir -p "$ETC" "$LIB" "$TMP" "$PLAY"

# Ensure default locations point into /data (persistence without relying on env)
# /etc/semaphore (config.json, secrets)
if [ -e /etc/semaphore ] && [ ! -L /etc/semaphore ]; then
  # If it's a real dir, replace it with a symlink (keep files if any)
  # Move contents once, then link.
  if [ -z "$(ls -A /etc/semaphore || true)" ]; then
    rmdir /etc/semaphore || true
  else
    cp -a /etc/semaphore/. "$ETC"/ 2>/dev/null || true
    rm -rf /etc/semaphore
  fi
fi
ln -sfn "$ETC" /etc/semaphore

# /var/lib/semaphore (Bolt DB and data)
if [ -e /var/lib/semaphore ] && [ ! -L /var/lib/semaphore ]; then
  if [ -z "$(ls -A /var/lib/semaphore || true)" ]; then
    rmdir /var/lib/semaphore || true
  else
    cp -a /var/lib/semaphore/. "$LIB"/ 2>/dev/null || true
    rm -rf /var/lib/semaphore
  fi
fi
ln -sfn "$LIB" /var/lib/semaphore

# /tmp/semaphore (temp/work dir)
if [ -e /tmp/semaphore ] && [ ! -L /tmp/semaphore ]; then
  rm -rf /tmp/semaphore
fi
ln -sfn "$TMP" /tmp/semaphore

# Basic perms (image may drop privileges internally; make writable for current user)
chown -R "$(id -u)":"$(id -g)" "$BASE" || true
chmod -R u+rwX,go+rX "$BASE" || true

# One-time bootstrap on first run only:
# If there is NO Bolt DB yet, export admin credentials so server-wrapper will create admin once.
DB_FILE="$LIB/database.boltdb"
if [ ! -f "$DB_FILE" ]; then
  if [ -f /data/options.json ]; then
    # Read HA add-on options (admin_* are your options in config.json)
    ADMIN_USER="$(jq -r '.admin_user // "admin"' /data/options.json 2>/dev/null || echo admin)"
    ADMIN_PASS="$(jq -r '.admin_password // "changeme"' /data/options.json 2>/dev/null || echo changeme)"
    ADMIN_NAME="$(jq -r '.admin_name // "Admin"' /data/options.json 2>/dev/null || echo Admin)"
    ADMIN_EMAIL="$(jq -r '.admin_email // "admin@example.com"' /data/options.json 2>/dev/null || echo admin@example.com)"
  else
    ADMIN_USER="admin"; ADMIN_PASS="changeme"; ADMIN_NAME="Admin"; ADMIN_EMAIL="admin@example.com"
  fi

  export SEMAPHORE_DB_DIALECT="bolt"
  # Use defaults; DB path is under /var/lib/semaphore via our symlink -> /data/semaphore/lib/database.boltdb
  export SEMAPHORE_ADMIN="$ADMIN_USER"
  export SEMAPHORE_ADMIN_PASSWORD="$ADMIN_PASS"
  export SEMAPHORE_ADMIN_NAME="$ADMIN_NAME"
  export SEMAPHORE_ADMIN_EMAIL="$ADMIN_EMAIL"

  # Persist cookie/crypto secrets so sessions survive restarts
  SECRETS_FILE="$ETC/secrets.env"
  if [ ! -f "$SECRETS_FILE" ]; then
    umask 077
    printf 'SEMAPHORE_COOKIE_HASH=%s\n'          "$(head -c 32 /dev/urandom | base64)" >  "$SECRETS_FILE"
    printf 'SEMAPHORE_COOKIE_ENCRYPTION=%s\n'     "$(head -c 32 /dev/urandom | base64)" >> "$SECRETS_FILE"
    printf 'SEMAPHORE_ACCESS_KEY_ENCRYPTION=%s\n' "$(head -c 32 /dev/urandom | base64)" >> "$SECRETS_FILE"
  fi
  # shellcheck disable=SC1090
  . "$SECRETS_FILE"
  export SEMAPHORE_COOKIE_HASH SEMAPHORE_COOKIE_ENCRYPTION SEMAPHORE_ACCESS_KEY_ENCRYPTION
fi

# Run from /data for good measure
cd /data

# Start upstream wrapper (correct path in Semaphore image)
# Tini warning can be silenced by env if needed; functionality is fine regardless.
exec /usr/local/bin/server-wrapper