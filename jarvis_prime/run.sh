#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH=/data/options.json

banner() {
  echo "──────────────────────────────────────────────"
  echo "🧠 $(jq -r '.bot_name' "$CONFIG_PATH") $(jq -r '.bot_icon' "$CONFIG_PATH")"
  echo "⚡ Boot sequence initiated..."
  echo "   → Personalities loaded"
  echo "   → Memory core mounted"
  echo "   → Network bridges linked"
  echo "   → LLM: $1"
  echo "   → Engine: $2"
  echo "   → Model path: $3"
  echo "   → WebSocket Intake: $4"
  echo "🚀 Systems online — Jarvis is awake!"
  echo "──────────────────────────────────────────────"
}

py_download() {
python3 - "$1" "$2" <<'PY'
import sys, os, urllib.request, shutil, pathlib
url, dst = sys.argv[1], sys.argv[2]
p = pathlib.Path(dst); p.parent.mkdir(parents=True, exist_ok=True)
tmp = str(p)+".part"
try:
    with urllib.request.urlopen(url) as r, open(tmp,"wb") as f:
        shutil.copyfileobj(r,f,1024*1024)
    os.replace(tmp, dst)
    print("[Downloader] Fetched ->", dst)
except Exception as e:
    try:
        if os.path.exists(tmp): os.remove(tmp)
    except: pass
    print("[Downloader] Failed:", e); sys.exit(1)
PY
}

# ===== Core options -> env =====
export BOT_NAME=$(jq -r '.bot_name' "$CONFIG_PATH")
export BOT_ICON=$(jq -r '.bot_icon' "$CONFIG_PATH")
export GOTIFY_URL=$(jq -r '.gotify_url' "$CONFIG_PATH")
export GOTIFY_CLIENT_TOKEN=$(jq -r '.gotify_client_token' "$CONFIG_PATH")
export GOTIFY_APP_TOKEN=$(jq -r '.gotify_app_token' "$CONFIG_PATH")
export JARVIS_APP_NAME=$(jq -r '.jarvis_app_name' "$CONFIG_PATH")
export RETENTION_HOURS=$(jq -r '.retention_hours' "$CONFIG_PATH")
export BEAUTIFY_ENABLED=$(jq -r '.beautify_enabled' "$CONFIG_PATH")
export SILENT_REPOST=$(jq -r '.silent_repost // "true"' "$CONFIG_PATH")
export INBOX_RETENTION_DAYS=$(jq -r '.retention_days // 30' "$CONFIG_PATH")
export AUTO_PURGE_POLICY=$(jq -r '.auto_purge_policy // "off"' "$CONFIG_PATH")

# Weather
export weather_enabled=$(jq -r '.weather_enabled // false' "$CONFIG_PATH")
export weather_lat=$(jq -r '.weather_lat // 0' "$CONFIG_PATH")
export weather_lon=$(jq -r '.weather_lon // 0' "$CONFIG_PATH")
export weather_city=$(jq -r '.weather_city // ""' "$CONFIG_PATH")
export weather_time=$(jq -r '.weather_time // "07:00"' "$CONFIG_PATH")

# Digest
export digest_enabled=$(jq -r '.digest_enabled // false' "$CONFIG_PATH")
export digest_time=$(jq -r '.digest_time // "08:00"' "$CONFIG_PATH")

# Radarr/Sonarr
export radarr_enabled=$(jq -r '.radarr_enabled // false' "$CONFIG_PATH")
export radarr_url=$(jq -r '.radarr_url // ""' "$CONFIG_PATH")
export radarr_api_key=$(jq -r '.radarr_api_key // ""' "$CONFIG_PATH")
export radarr_time=$(jq -r '.radarr_time // "07:30"' "$CONFIG_PATH")
export sonarr_enabled=$(jq -r '.sonarr_enabled // false' "$CONFIG_PATH")
export sonarr_url=$(jq -r '.sonarr_url // ""' "$CONFIG_PATH")
export sonarr_api_key=$(jq -r '.sonarr_api_key // ""' "$CONFIG_PATH")
export sonarr_time=$(jq -r '.sonarr_time // "07:30"' "$CONFIG_PATH")

# Technitium DNS
export TECHNITIUM_ENABLED=$(jq -r '.technitium_enabled // false' "$CONFIG_PATH")
export TECHNITIUM_URL=$(jq -r '.technitium_url // ""' "$CONFIG_PATH")
export TECHNITIUM_API_KEY=$(jq -r '.technitium_api_key // ""' "$CONFIG_PATH")
export TECHNITIUM_USER=$(jq -r '.technitium_user // ""' "$CONFIG_PATH")
export TECHNITIUM_PASS=$(jq -r '.technitium_pass // ""' "$CONFIG_PATH")
export technitium_enabled="$TECHNITIUM_ENABLED"
export technitium_url="$TECHNITIUM_URL"
export technitium_api_key="$TECHNITIUM_API_KEY"
export technitium_user="$TECHNITIUM_USER"
export technitium_pass="$TECHNITIUM_PASS"

# Uptime Kuma
export UPTIMEKUMA_ENABLED=$(jq -r '.uptimekuma_enabled // false' "$CONFIG_PATH")
export UPTIMEKUMA_URL=$(jq -r '.uptimekuma_url // ""' "$CONFIG_PATH")
export UPTIMEKUMA_API_KEY=$(jq -r '.uptimekuma_api_key // ""' "$CONFIG_PATH")
export UPTIMEKUMA_STATUS_SLUG=$(jq -r '.uptimekuma_status_slug // ""' "$CONFIG_PATH")
export uptimekuma_enabled="$UPTIMEKUMA_ENABLED"
export uptimekuma_url="$UPTIMEKUMA_URL"
export uptimekuma_api_key="$UPTIMEKUMA_API_KEY"
export uptimekuma_status_slug="$UPTIMEKUMA_STATUS_SLUG"

# SMTP intake
export SMTP_ENABLED=$(jq -r '.smtp_enabled // false' "$CONFIG_PATH")
export SMTP_BIND=$(jq -r '.smtp_bind // "0.0.0.0"' "$CONFIG_PATH")
export SMTP_PORT=$(jq -r '.smtp_port // 2525' "$CONFIG_PATH")
export SMTP_MAX_BYTES=$(jq -r '.smtp_max_bytes // 262144' "$CONFIG_PATH")
export SMTP_DUMMY_RCPT=$(jq -r '.smtp_dummy_rcpt // "alerts@jarvis.local"' "$CONFIG_PATH")
export SMTP_ACCEPT_ANY_AUTH=$(jq -r '.smtp_accept_any_auth // true' "$CONFIG_PATH")
export SMTP_REWRITE_TITLE_PREFIX=$(jq -r '.smtp_rewrite_title_prefix // "[SMTP]"' "$CONFIG_PATH")
export SMTP_ALLOW_HTML=$(jq -r '.smtp_allow_html // false' "$CONFIG_PATH")
export SMTP_PRIORITY_DEFAULT=$(jq -r '.smtp_priority_default // 5' "$CONFIG_PATH")
export SMTP_PRIORITY_MAP=$(jq -r '.smtp_priority_map // "{}"' "$CONFIG_PATH")

# Proxy
export PROXY_ENABLED=$(jq -r '.proxy_enabled // false' "$CONFIG_PATH")
export PROXY_BIND=$(jq -r '.proxy_bind // "0.0.0.0"' "$CONFIG_PATH")
export PROXY_PORT=$(jq -r '.proxy_port // 2580' "$CONFIG_PATH")
export PROXY_GOTIFY_URL=$(jq -r '.proxy_gotify_url // ""' "$CONFIG_PATH")
export PROXY_NTFY_URL=$(jq -r '.proxy_ntfy_url // ""' "$CONFIG_PATH")

# ntfy
export NTFY_URL=$(jq -r '.ntfy_url // ""' "$CONFIG_PATH")
export NTFY_TOPIC=$(jq -r '.ntfy_topic // ""' "$CONFIG_PATH")
export NTFY_USER=$(jq -r '.ntfy_user // ""' "$CONFIG_PATH")
export NTFY_PASS=$(jq -r '.ntfy_pass // ""' "$CONFIG_PATH")
export NTFY_TOKEN=$(jq -r '.ntfy_token // ""' "$CONFIG_PATH")

# Push toggles
export push_gotify_enabled=$(jq -r '.push_gotify_enabled // false' "$CONFIG_PATH")
export push_ntfy_enabled=$(jq -r '.push_ntfy_enabled // false' "$CONFIG_PATH")

echo "[launcher] toggles: push_gotify_enabled=$push_gotify_enabled, push_ntfy_enabled=$push_ntfy_enabled"

if [ "$push_gotify_enabled" != "true" ] && [ "$push_gotify_enabled" != "1" ]; then
  export GOTIFY_URL=""
  export GOTIFY_CLIENT_TOKEN=""
  export GOTIFY_APP_TOKEN=""
  echo "[launcher] hard-off: Gotify pushes disabled (env blanked)"
fi

if [ "$push_ntfy_enabled" != "true" ] && [ "$push_ntfy_enabled" != "1" ]; then
  export NTFY_URL=""
  export NTFY_TOPIC=""
  echo "[launcher] hard-off: ntfy pushes disabled (env blanked)"
fi

# Personalities
export CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")

# LLM controls … (unchanged)

# ===== Inbox service =====
export JARVIS_API_BIND="0.0.0.0"; export JARVIS_API_PORT="2581"
export JARVIS_DB_PATH="/data/jarvis.db"
if [ -d "/share/jarvis_prime/ui" ]; then
  export JARVIS_UI_DIR="/share/jarvis_prime/ui"
else
  export JARVIS_UI_DIR="/app/ui"
fi
mkdir -p "$JARVIS_UI_DIR" || true

# ===== RAG refresher … (unchanged)

# ===== WebSocket intake flags =====
WS_ENABLED=$(jq -r '.intake_ws_enabled // false' "$CONFIG_PATH")
WS_PORT=$(jq -r '.intake_ws_port // 8765' "$CONFIG_PATH")

# Banner
BANNER_LLM="$( [ "$LLM_ENABLED" = "true" ] && echo "$LLM_STATUS" || echo "Disabled" )"
BANNER_WS="$( [ "$WS_ENABLED" = "true" ] && echo "Enabled (port $WS_PORT)" || echo "Disabled" )"
banner "$BANNER_LLM" "$ENGINE" "${LLM_MODEL_PATH:-}" "$BANNER_WS"

echo "[launcher] URLs: gotify=$GOTIFY_URL ntfy=${NTFY_URL:-}"
echo "[launcher] starting inbox server (api_messages.py) on :$JARVIS_API_PORT"
python3 /app/api_messages.py &
API_PID=$!

# ===== SMTP intake =====
if [[ "${SMTP_ENABLED}" == "true" ]]; then
  echo "[launcher] starting SMTP intake (smtp_server.py) on ${SMTP_BIND}:${SMTP_PORT}"
  python3 /app/smtp_server.py &
  SMTP_PID=$! || true
else
  echo "[launcher] SMTP disabled"
fi

# ===== Proxy + Bot =====
if [[ "${PROXY_ENABLED}" == "true" ]]; then
  echo "[launcher] starting proxy (proxy.py)"; python3 /app/proxy.py & PROXY_PID=$! || true
  echo "[launcher] starting bot (bot.py)";    python3 /app/bot.py    & BOT_PID=$!   || true
else
  echo "[launcher] proxy disabled"
fi

# ===== WebSocket intake =====
if [[ "${WS_ENABLED}" == "true" ]]; then
  echo "[launcher] starting WebSocket intake (websocket.py) on :${WS_PORT}"
  python3 /app/websocket.py &
  WS_PID=$! || true
  echo "[launcher] WebSocket intake started ✅"
else
  echo "[launcher] WebSocket intake disabled"
fi

wait "$API_PID"