#!/usr/bin/with-contenv bashio
set -e

# Setup environment
mkdir -p /root/.ssh
cp -R /config/.ssh/* /root/.ssh/ 2>/dev/null || true
chmod -R 600 /root/.ssh/* 2>/dev/null || true
chmod 700 /root/.ssh

# Export Supervisor token
export SUPERVISOR_TOKEN=$(bashio::supervisor.token)

# Run Python updater
exec python3 /updater.py
