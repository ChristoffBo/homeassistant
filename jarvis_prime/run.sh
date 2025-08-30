#!/usr/bin/env bash
set -euo pipefail

OPTS=/data/options.json
JQ="jq -r"

log(){ printf '[launcher] %s\n' "$*"; }

# Safe read (value or empty)
get(){ $JQ "$1 // empty" "$OPTS"; }

# ---- Map options -> environment ----
export BOT_NAME="$(get '.bot_name')"
export BOT_ICON="$(get '.bot_icon')"

export GOTIFY_URL="$(get '.gotify_url')"
export GOTIFY_CLIENT_TOKEN="$(get '.gotify_client_token')"
export GOTIFY_APP_TOKEN="$(get '.gotify_app_token')"

export NTFY_URL="$(get '.ntfy_url')"
export NTFY_TOPIC="$(get '.ntfy_topic')"
export NTFY_USER="$(get '.ntfy_user')"
export NTFY_PASS="$(get '.ntfy_pass')"
export NTFY_TOKEN="$(get '.ntfy_token')"

export INBOX_RETENTION_DAYS="$(get '.retention_days')"

export SMTP_ENABLED="$(get '.smtp_enabled')"
export SMTP_BIND="$(get '.smtp_bind')"
export SMTP_PORT="$(get '.smtp_port')"

export PROXY_ENABLED="$(get '.proxy_enabled')"
export PROXY_BIND="$(get '.proxy_bind')"
export PROXY_PORT="$(get '.proxy_port')"

export TECHNITIUM_ENABLED="$(get '.technitium_enabled')"
export TECHNITIUM_URL="$(get '.technitium_url')"
export TECHNITIUM_API_KEY="$(get '.technitium_api_key')"
export TECHNITIUM_USER="$(get '.technitium_user')"
export TECHNITIUM_PASS="$(get '.technitium_pass')"

export UPTIMEKUMA_ENABLED="$(get '.uptimekuma_enabled')"
export UPTIMEKUMA_URL="$(get '.uptimekuma_url')"
export UPTIMEKUMA_API_KEY="$(get '.uptimekuma_api_key')"
export UPTIMEKUMA_STATUS_SLUG="$(get '.uptimekuma_status_slug')"

# Fan-out toggles (optional)
export PUSH_NOTIFY_GOTIFY="$(get '.push_gotify_enabled')"
export PUSH_NOTIFY_NTFY="$(get '.push_ntfy_enabled')"
export PUSH_NOTIFY_SMTP="$(get '.push_smtp_enabled')"

# Inbox server parameters
export JARVIS_API_BIND="0.0.0.0"
export JARVIS_API_PORT="2581"
export JARVIS_DB_PATH="/data/jarvis.db"
export JARVIS_UI_DIR="/app/ui"

log "URLs:   gotify=$GOTIFY_URL ntfy=$NTFY_URL"
log "starting inbox server (api_messages.py) on :$JARVIS_API_PORT"
python3 /app/api_messages.py &
API_PID=$!

if [[ "${SMTP_ENABLED}" == "true" ]]; then
  log "starting SMTP intake (smtp_server.py) on ${SMTP_BIND:-0.0.0.0}:${SMTP_PORT:-2525}"
  python3 /app/smtp_server.py &
  SMTP_PID=$!
else
  log "SMTP disabled"
fi

if [[ "${PROXY_ENABLED}" == "true" ]]; then
  log "starting proxy (proxy.py)"
  python3 /app/proxy.py &
  PROXY_PID=$!
  log "starting bot (bot.py)"
  python3 /app/bot.py &
  BOT_PID=$!
else
  log "proxy disabled"
fi

# Wait on children
wait "$API_PID"
