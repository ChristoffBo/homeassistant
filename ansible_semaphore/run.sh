#!/usr/bin/env bash
set -euo pipefail

# Persist everything under /data
export BASE="/data/semaphore"
export SEMAPHORE_CONFIG_PATH="$BASE"
export SEMAPHORE_TMP_PATH="$BASE/tmp"
export SEMAPHORE_PLAYBOOK_PATH="$BASE/playbooks"
export SEMAPHORE_DB_DIALECT="${SEMAPHORE_DB_DIALECT:-bolt}"
export SEMAPHORE_DB="${SEMAPHORE_DB:-$BASE/semaphore.db}"

# One-time secrets (persisted) so sessions & logins keep working across restarts
SECRETS_FILE="$BASE/secrets.env"
mkdir -p "$BASE" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"
if [ ! -f "$SECRETS_FILE" ]; then
  umask 077
  printf 'SEMAPHORE_COOKIE_HASH=%s\n'            "$(head -c 32 /dev/urandom | base64)" >  "$SECRETS_FILE"
  printf 'SEMAPHORE_COOKIE_ENCRYPTION=%s\n'       "$(head -c 32 /dev/urandom | base64)" >> "$SECRETS_FILE"
  printf 'SEMAPHORE_ACCESS_KEY_ENCRYPTION=%s\n'   "$(head -c 32 /dev/urandom | base64)" >> "$SECRETS_FILE"
fi
# shellcheck disable=SC1090
. "$SECRETS_FILE"
export SEMAPHORE_COOKIE_HASH SEMAPHORE_COOKIE_ENCRYPTION SEMAPHORE_ACCESS_KEY_ENCRYPTION

# Ensure current runtime user can write the tree (root or image user)
chown -R "$(id -u)":"$(id -g)" "$BASE" || true

# Run from /data and start the upstream wrapper (correct binary path)
cd /data
exec /usr/local/bin/server-wrapper