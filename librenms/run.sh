#!/usr/bin/env bash
set -e

echo "[INFO] Starting LibreNMS add-on..."

# Best-effort update (offline-safe)
apt-get update || true
apt-get upgrade -y || true

# Start LibreNMS (LinuxServer entrypoint handles init)
/init