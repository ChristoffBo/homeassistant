#!/bin/sh
set -e

echo "[INFO] Starting Ansible Semaphore add-on..."

# Ensure persistent directories
mkdir -p /share/ansible_semaphore/tmp
mkdir -p /share/ansible_semaphore/projects

# Start Semaphore with BoltDB in /share
exec /usr/bin/semaphore \
  --config /share/ansible_semaphore/config.json \
  --bolt /share/ansible_semaphore/database.boltdb \
  --tmp /share/ansible_semaphore/tmp \
  --port 3000