#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json
log() { echo "[$(jq -r '.bot_name' "$CONFIG_PATH")] $*"; }

# Core
export BOT_NAME=$(jq -r '.bot_name' "$CONFIG_PATH")
export BOT_ICON=$(jq -r '.bot_icon' "$CONFIG_PATH")
export GOTIFY_URL=$(jq -r '.gotify_url' "$CONFIG_PATH")
export GOTIFY_CLIENT_TOKEN=$(jq -r '.gotify_client_token' "$CONFIG_PATH")
export GOTIFY_APP_TOKEN=$(jq -r '.gotify_app_token' "$CONFIG_PATH")
export JARVIS_APP_NAME=$(jq -r '.jarvis_app_name' "$CONFIG_PATH")

export RETENTION_HOURS=$(jq -r '.retention_hours' "$CONFIG_PATH")
export BEAUTIFY_ENABLED=$(jq -r '.beautify_enabled' "$CONFIG_PATH")
export SILENT_REPOST=$(jq -r '.silent_repost // "true"' "$CONFIG_PATH")

# Weather
export WEATHER_ENABLED=$(jq -r '.weather_enabled' "$CONFIG_PATH")
export WEATHER_API=$(jq -r '.weather_api // ""' "$CONFIG_PATH")
export WEATHER_API_KEY=$(jq -r '.weather_api_key // ""' "$CONFIG_PATH")
export WEATHER_CITY=$(jq -r '.weather_city' "$CONFIG_PATH")
export WEATHER_TIME=$(jq -r '.weather_time' "$CONFIG_PATH")

# Digest
export DIGEST_ENABLED=$(jq -r '.digest_enabled' "$CONFIG_PATH")
export DIGEST_TIME=$(jq -r '.digest_time' "$CONFIG_PATH")

# Radarr
export RADARR_ENABLED=$(jq -r '.radarr_enabled' "$CONFIG_PATH")
export RADARR_URL=$(jq -r '.radarr_url' "$CONFIG_PATH")
export RADARR_API_KEY=$(jq -r '.radarr_api_key' "$CONFIG_PATH")
export RADARR_TIME=$(jq -r '.radarr_time' "$CONFIG_PATH")

# Sonarr
export SONARR_ENABLED=$(jq -r '.sonarr_enabled' "$CONFIG_PATH")
export SONARR_URL=$(jq -r '.sonarr_url' "$CONFIG_PATH")
export SONARR_API_KEY=$(jq -r '.sonarr_api_key' "$CONFIG_PATH")
export SONARR_TIME=$(jq -r '.sonarr_time' "$CONFIG_PATH")

# Technitium DNS
export technitium_enabled=$(jq -r '.technitium_enabled' "$CONFIG_PATH")
export technitium_url=$(jq -r '.technitium_url' "$CONFIG_PATH")
export technitium_api_key=$(jq -r '.technitium_api_key // ""' "$CONFIG_PATH")
export technitium_user=$(jq -r '.technitium_user // ""' "$CONFIG_PATH")
export technitium_pass=$(jq -r '.technitium_pass // ""' "$CONFIG_PATH")

# Uptime Kuma
export uptimekuma_enabled=$(jq -r '.uptimekuma_enabled' "$CONFIG_PATH")
export uptimekuma_url=$(jq -r '.uptimekuma_url' "$CONFIG_PATH")
export uptimekuma_api_key=$(jq -r '.uptimekuma_api_key // ""' "$CONFIG_PATH")
export uptimekuma_status_slug=$(jq -r '.uptimekuma_status_slug // ""' "$CONFIG_PATH")

# SMTP intake
export smtp_enabled=$(jq -r '.smtp_enabled' "$CONFIG_PATH")
export smtp_bind=$(jq -r '.smtp_bind // "0.0.0.0"' "$CONFIG_PATH")
export smtp_port=$(jq -r '.smtp_port // 2525' "$CONFIG_PATH")
export smtp_max_bytes=$(jq -r '.smtp_max_bytes // 262144' "$CONFIG_PATH")
export smtp_dummy_rcpt=$(jq -r '.smtp_dummy_rcpt // "alerts@jarvis.local"' "$CONFIG_PATH")
export smtp_accept_any_auth=$(jq -r '.smtp_accept_any_auth // true' "$CONFIG_PATH")
export smtp_rewrite_title_prefix=$(jq -r '.smtp_rewrite_title_prefix // "[SMTP]"' "$CONFIG_PATH")
export smtp_allow_html=$(jq -r '.smtp_allow_html // false' "$CONFIG_PATH")
export smtp_priority_default=$(jq -r '.smtp_priority_default // 5' "$CONFIG_PATH")
export smtp_priority_map=$(jq -r '.smtp_priority_map // "{}"' "$CONFIG_PATH")

# Proxy (Gotify + ntfy)
export proxy_enabled=$(jq -r '.proxy_enabled' "$CONFIG_PATH")
export proxy_bind=$(jq -r '.proxy_bind // "0.0.0.0"' "$CONFIG_PATH")
export proxy_port=$(jq -r '.proxy_port // 2580' "$CONFIG_PATH")
export proxy_gotify_url=$(jq -r '.proxy_gotify_url // ""' "$CONFIG_PATH")
export proxy_ntfy_url=$(jq -r '.proxy_ntfy_url // ""' "$CONFIG_PATH")

log "Starting add-on..."
exec python3 /app/bot.py
