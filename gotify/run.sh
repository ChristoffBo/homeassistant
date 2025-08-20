#!/usr/bin/env sh
set -e

# Prepare persistent dirs inside /config
mkdir -p /config/gotify /config/gotify/images /config/gotify/plugins

# Force Gotify to use /config for all persistence
export GOTIFY_DATABASE_DIALECT=sqlite3
export GOTIFY_DATABASE_CONNECTION=/config/gotify/gotify.db
export GOTIFY_UPLOADEDIMAGESDIR=/config/gotify/images
export GOTIFY_PLUGINSDIR=/config/gotify/plugins
export GOTIFY_SERVER_PORT=80

# Start Gotify (official image binary path)
exec /app/gotify-app