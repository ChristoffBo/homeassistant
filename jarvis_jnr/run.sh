#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

# Log helper
log() { echo "[$BOT_NAME] $*"; }

CONFIG_PATH=/data/options.json

# -----------------------------------------------------------
# Export bot environment variables from options.json
# -----------------------------------------------------------
export BOT_NAME=$(jq -r '.bot_name' $CONFIG_PATH)
export BOT_ICON=$(jq -r '.bot_icon' $CONFIG_PATH)
export GOTIFY_URL=$(jq -r '.gotify_url' $CONFIG_PATH)
export GOTIFY_CLIENT_TOKEN=$(jq -r '.gotify_client_token' $CONFIG_PATH)
export GOTIFY_APP_TOKEN=$(jq -r '.gotify_app_token' $CONFIG_PATH)
export JARVIS_APP_NAME=$(jq -r '.jarvis_app_name' $CONFIG_PATH)

export RETENTION_HOURS=$(jq -r '.retention_hours' $CONFIG_PATH)
export BEAUTIFY_ENABLED=$(jq -r '.beautify_enabled' $CONFIG_PATH)
export COMMANDS_ENABLED=$(jq -r '.commands_enabled' $CONFIG_PATH)

export QUIET_HOURS_ENABLED=$(jq -r '.quiet_hours_enabled' $CONFIG_PATH)
export QUIET_HOURS=$(jq -r '.quiet_hours' $CONFIG_PATH)

export WEATHER_ENABLED=$(jq -r '.weather_enabled' $CONFIG_PATH)
export WEATHER_API=$(jq -r '.weather_api' $CONFIG_PATH)
export WEATHER_API_KEY=$(jq -r '.weather_api_key' $CONFIG_PATH)
export WEATHER_CITY=$(jq -r '.weather_city' $CONFIG_PATH)
export WEATHER_TIME=$(jq -r '.weather_time' $CONFIG_PATH)

export DIGEST_ENABLED=$(jq -r '.digest_enabled' $CONFIG_PATH)
export DIGEST_TIME=$(jq -r '.digest_time' $CONFIG_PATH)

export RADARR_ENABLED=$(jq -r '.radarr_enabled' $CONFIG_PATH)
export RADARR_URL=$(jq -r '.radarr_url' $CONFIG_PATH)
export RADARR_API_KEY=$(jq -r '.radarr_api_key' $CONFIG_PATH)
export RADARR_TIME=$(jq -r '.radarr_time' $CONFIG_PATH)

export SONARR_ENABLED=$(jq -r '.sonarr_enabled' $CONFIG_PATH)
export SONARR_URL=$(jq -r '.sonarr_url' $CONFIG_PATH)
export SONARR_API_KEY=$(jq -r '.sonarr_api_key' $CONFIG_PATH)
export SONARR_TIME=$(jq -r '.sonarr_time' $CONFIG_PATH)

# -----------------------------------------------------------
# Newly added toggles
# -----------------------------------------------------------
export SILENT_REPOST=$(jq -r '.silent_repost' $CONFIG_PATH)
export ENABLE_BULK_PURGE=$(jq -r '.enable_bulk_purge' $CONFIG_PATH)

# -----------------------------------------------------------
# Log start with dynamic bot name
# -----------------------------------------------------------
log "Starting add-on..."

# -----------------------------------------------------------
# Launch bot
# -----------------------------------------------------------
exec python3 /app/bot.py
