#!/usr/bin/with-contenv bashio

# Ensure data directory exists
mkdir -p /data

# Create symbolic link from /tugtainer to /data if it doesn't exist
if [ ! -L "/tugtainer" ]; then
    rm -rf /tugtainer
    ln -s /data /tugtainer
fi

bashio::log.info "Starting Tugtainer..."
bashio::log.info "Data directory: /data"

# Start Tugtainer (the original entrypoint)
exec /docker-entrypoint.sh
