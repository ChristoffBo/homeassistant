#!/usr/bin/with-contenv bashio

# Start NGINX in background
nginx

# Start Python application
cd /app || exit
exec python3 -m app.main