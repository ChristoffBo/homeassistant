#!/usr/bin/with-contenv bashio
set -e

# Setup SSH keys if they exist
if [ -d "/config/.ssh" ]; then
    mkdir -p /root/.ssh
    cp -R /config/.ssh/* /root/.ssh/
    chmod 600 /root/.ssh/*
    chmod 700 /root/.ssh
fi

# Export Supervisor token
export SUPERVISOR_TOKEN=$(bashio::supervisor.token)

# Run Python updater
python3 /updater.py

bashio::log.info "Addon update process completed"
