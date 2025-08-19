#!/usr/bin/env bash
set -e

# Use /data (Supervisor persistent storage) instead of /config or /share
cd /data

# Launch Semaphore
exec /usr/bin/semaphore server