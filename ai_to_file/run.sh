#!/usr/bin/with-contenv bashio

# Change to app directory
cd /app || exit

# Run the application
exec python3 /app/main.py