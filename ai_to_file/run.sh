#!/usr/bin/with-contenv bashio

# Change to app directory
cd /app || exit

# Execute main.py directly (not as module)
exec python3 /app/main.py