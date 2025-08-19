#!/usr/bin/env bash
set -e

# Use /data (Supervisor persistent storage)
cd /data

# Launch Semaphore
exec /usr/bin/semaphore server