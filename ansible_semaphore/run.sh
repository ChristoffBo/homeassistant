#!/bin/sh
set -e

echo "[INFO] Starting Ansible Semaphore add-on..."

# Ensure persistent directories under /share
mkdir -p /share/ansible_semaphore/tmp
mkdir -p /share/ansible_semaphore/projects

# Generate default config.json if missing
if [ ! -f /share/ansible_semaphore/config.json ]; then
  echo "[INFO] Generating default Semaphore config..."
  cat <<EOF > /share/ansible_semaphore/config.json
{
  "dialect": "bolt",
  "bolt": {
    "file": "/share/ansible_semaphore/database.boltdb"
  },
  "tmp_path": "/share/ansible_semaphore/tmp",
  "projects_path": "/share/ansible_semaphore/projects",
  "port": "3000"
}
EOF
fi

# Start Semaphore using BoltDB in /share
exec /usr/bin/semaphore \
  --config /share/ansible_semaphore/config.json