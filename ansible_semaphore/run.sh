#!/usr/bin/env bash
set -e

# Use environment variables passed from config.json instead of bashio
PORT=${PORT:-10443}
ADMIN_USER=${ADMIN_USER:-admin}
ADMIN_EMAIL=${ADMIN_EMAIL:-admin@example.com}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-changeme}

mkdir -p /data
cd /data

if [ ! -f /data/semaphore_config.json ]; then
    echo "Initializing Semaphore with SQLite..."
    /usr/local/bin/semaphore setup \
      --config /data/semaphore_config.json \
      --db sqlite3 /data/semaphore.db \
      --admin "$ADMIN_USER" \
      --admin-email "$ADMIN_EMAIL" \
      --admin-password "$ADMIN_PASSWORD" \
      --access-key $(uuidgen) \
      --tmp-path /tmp/semaphore \
      --playbook-path /data/playbooks \
      --port "$PORT"
fi

echo "Starting Ansible Semaphore..."
exec /usr/local/bin/semaphore server --config /data/semaphore_config.json
