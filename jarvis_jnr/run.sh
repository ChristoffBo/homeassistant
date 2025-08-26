#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json
log() { echo "[$(jq -r '.bot_name' $CONFIG_PATH)] $*"; }

# Core
export BOT_NAME=$(jq -r '.bot_name' $CONFIG_PATH)
export BOT_ICON=$(jq -r '.bot_icon' $CONFIG_PATH)
export GOTIFY_URL=$(jq -r '.gotify_url' $CONFIG_PATH)
export GOTIFY_CLIENT_TOKEN=$(jq -r '.gotify_client_token' $CONFIG_PATH)
export GOTIFY_APP_TOKEN=$(jq -r '.gotify_app_token' $CONFIG_PATH)
export JARVIS_APP_NAME=$(jq -r '.jarvis_app_name' $CONFIG_PATH)

export RETENTION_HOURS=$(jq -r '.retention_hours' $CONFIG_PATH)
export BEAUTIFY_ENABLED=$(jq -r '.beautify_enabled' $CONFIG_PATH)
export SILENT_REPOST=$(jq -r '.silent_repost // "true"' $CONFIG_PATH)

# Weather
export WEATHER_ENABLED=$(jq -r '.weather_enabled' $CONFIG_PATH)
export WEATHER_API=$(jq -r '.weather_api // ""' $CONFIG_PATH)
export WEATHER_API_KEY=$(jq -r '.weather_api_key // ""' $CONFIG_PATH)
export WEATHER_CITY=$(jq -r '.weather_city' $CONFIG_PATH)
export WEATHER_TIME=$(jq -r '.weather_time' $CONFIG_PATH)

# Digest
export DIGEST_ENABLED=$(jq -r '.digest_enabled' $CONFIG_PATH)
export DIGEST_TIME=$(jq -r '.digest_time' $CONFIG_PATH)

# Radarr
export RADARR_ENABLED=$(jq -r '.radarr_enabled' $CONFIG_PATH)
export RADARR_URL=$(jq -r '.radarr_url' $CONFIG_PATH)
export RADARR_API_KEY=$(jq -r '.radarr_api_key' $CONFIG_PATH)
export RADARR_TIME=$(jq -r '.radarr_time' $CONFIG_PATH)

# Sonarr
export SONARR_ENABLED=$(jq -r '.sonarr_enabled' $CONFIG_PATH)
export SONARR_URL=$(jq -r '.sonarr_url' $CONFIG_PATH)
export SONARR_API_KEY=$(jq -r '.sonarr_api_key' $CONFIG_PATH)
export SONARR_TIME=$(jq -r '.sonarr_time' $CONFIG_PATH)

# Technitium DNS
export technitium_enabled=$(jq -r '.technitium_enabled' $CONFIG_PATH)
export technitium_url=$(jq -r '.technitium_url' $CONFIG_PATH)
export technitium_api_key=$(jq -r '.technitium_api_key' $CONFIG_PATH)

log "Starting add-on..."
exec python3 /app/bot.py
