#!/usr/bin/with-contenv bashio

# Change to app directory
cd /app || exit

# Execute main.py directly
exec python3 main.py
