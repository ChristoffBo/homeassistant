#!/usr/bin/env bash
set -e

# Upgrade base system best-effort
apt-get update || true
apt-get -y upgrade || true

# Ensure storage exists
mkdir -p /data
cd /data

if [ ! -f /data/semaphore_config.json ]; then
    echo "Initializing Semaphore with SQLite..."
    semaphore setup \
      --config /data/semaphore_config.json \
      --db sqlite3 /data/semaphore.db \
      --admin $(bashio::config 'admin_user') \
      --admin-email $(bashio::config 'admin_email') \
      --admin-password $(bashio::config 'admin_password') \
      --access-key $(uuidgen) \
      --tmp-path /tmp/semaphore \
      --playbook-path /data/playbooks \
      --port $(bashio::config 'port')
fi

echo "Starting Ansible Semaphore..."
exec semaphore server --config /data/semaphore_config.json
