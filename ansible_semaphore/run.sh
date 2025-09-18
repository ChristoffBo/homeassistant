#!/bin/sh
set -e

echo "[semaphore-addon] Writing Semaphore config → /etc/semaphore/config.json"

cat >/etc/semaphore/config.json <<EOF
{
  "sqlite": {
    "file": "${SEMAPHORE_DB_HOST:-/share/ansible_semaphore/semaphore.db}"
  },
  "tmp_path": "${SEMAPHORE_TMP_PATH:-/tmp/semaphore}",
  "cookie_hash": "${SEMAPHORE_COOKIE_HASH}",
  "cookie_encryption": "${SEMAPHORE_COOKIE_ENCRYPTION}",
  "access_key_encryption": "${SEMAPHORE_ACCESS_KEY_ENCRYPTION}",
  "web_host": "0.0.0.0",
  "web_port": "${SEMAPHORE_PORT:-8055}",
  "web_root": "",
  "playbook_path": "${SEMAPHORE_PLAYBOOK_PATH:-/share/ansible_semaphore/playbooks}",
  "non_auth": false
}
EOF

echo "[semaphore-addon] Ensuring data paths..."
mkdir -p /share/ansible_semaphore/playbooks
touch /share/ansible_semaphore/semaphore.db

echo "[semaphore-addon] Starting Semaphore..."
exec /usr/local/bin/semaphore server --config /etc/semaphore/config.json