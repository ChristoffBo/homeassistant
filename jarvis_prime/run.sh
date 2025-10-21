#!/usr/bin/env bash
set -euo pipefail

# --- UTF-8 Locale Fix (safe for all modules) ---
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
# ----------------------------------------------

CONFIG_PATH=/data/options.json

############################################
# System Package Self-Heal (Debian Base)
############################################
echo "[init] Updating base system packages..."
apt-get update -y >/dev/null 2>&1 || true
apt-get upgrade -y >/dev/null 2>&1 || true

echo "[init] Installing required network tools (arp-scan, iproute2, dnsutils)..."
apt-get install -y --no-install-recommends arp-scan iproute2 dnsutils >/dev/null 2>&1 || true
echo "[init] Network utilities ready."

# === NEW FIX: enable HTTPS for ntfy ===
echo "[init] Installing CA certificates and curl for HTTPS support..."
apt-get install -y --no-install-recommends ca-certificates curl python3-requests >/dev/null 2>&1 || true
update-ca-certificates >/dev/null 2>&1 || true
echo "[init] HTTPS stack ready."

banner() {
  local llm="$1"
  local engine="$2"
  local model="$3"
  local ws="$4"
  echo "──────────────────────────────────────────────"
  echo "🧠 $(jq -r '.bot_name' "$CONFIG_PATH") $(jq -r '.bot_icon' "$CONFIG_PATH")"
  echo "⚡ Boot sequence initiated..."
  echo "   → Personalities loaded"
  echo "   → Memory core mounted"
  echo "   → Network bridges linked"
  echo "   → LLM: $llm"
  echo "   → Engine: $engine"
  echo "   → Model path: $model"
  echo "   → WebSocket Intake: $ws"
  echo "🚀 Systems online — Jarvis is awake!"
  echo "──────────────────────────────────────────────"
  echo "Modules:"
  [[ "$(jq -r '.radarr_enabled' "$CONFIG_PATH")" == "true" ]]     && echo "🎬 Radarr — ACTIVE" || echo "🎬 Radarr — DISABLED"
  [[ "$(jq -r '.sonarr_enabled' "$CONFIG_PATH")" == "true" ]]     && echo "📺 Sonarr — ACTIVE" || echo "📺 Sonarr — DISABLED"
  [[ "$(jq -r '.weather_enabled' "$CONFIG_PATH")" == "true" ]]    && echo "🌤️ Weather — ACTIVE" || echo "🌤️ Weather — DISABLED"
  [[ "$(jq -r '.digest_enabled' "$CONFIG_PATH")" == "true" ]]     && echo "🧾 Digest — ACTIVE" || echo "🧾 Digest — DISABLED"
  [[ "$(jq -r '.llm_enabled' "$CONFIG_PATH")" == "true" ]]        && echo "💬 Chat — ACTIVE" || echo "💬 Chat — DISABLED"
  [[ "$(jq -r '.uptimekuma_enabled' "$CONFIG_PATH")" == "true" ]] && echo "📈 Uptime Kuma — ACTIVE" || echo "📈 Uptime Kuma — DISABLED"
  [[ "$(jq -r '.smtp_enabled' "$CONFIG_PATH")" == "true" ]]       && echo "✉️ SMTP Intake — ACTIVE" || echo "✉️ SMTP Intake — DISABLED"
  [[ "$(jq -r '.proxy_enabled' "$CONFIG_PATH")" == "true" ]]      && echo "🔀 Proxy Intake — ACTIVE" || echo "🔀 Proxy Intake — DISABLED"
  [[ "$(jq -r '.technitium_enabled' "$CONFIG_PATH")" == "true" ]] && echo "🧠 DNS (Technitium) — ACTIVE" || echo "🧠 DNS (Technitium) — DISABLED"
  echo "🔗 Webhook Intake — ACTIVE"
  echo "📮 Apprise Intake — ACTIVE"
  [[ "$(jq -r '.llm_enviroguard_enabled' "$CONFIG_PATH")" == "true" ]] && echo "🌡️ EnviroGuard — ACTIVE" || echo "🌡️ EnviroGuard — DISABLED"
  [[ "$ws" == Disabled* ]] && echo "🔌 WebSocket Intake — DISABLED" || echo "🔌 WebSocket Intake — ACTIVE ($ws)"
  echo ""
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

############################################
# Jarvis Prime — Default Playbook Loader
############################################
mkdir -p /share/jarvis_prime
if [ ! -d /share/jarvis_prime/playbooks ] || [ -z "$(ls -A /share/jarvis_prime/playbooks 2>/dev/null)" ]; then
  echo "[init] No user playbooks found — loading defaults..."
  mkdir -p /share/jarvis_prime/playbooks
  cp -r /playbooks/defaults/* /share/jarvis_prime/playbooks/ 2>/dev/null || true
else
  echo "[init] User playbooks detected — skipping defaults."
fi

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

# Uptime Kuma
export UPTIMEKUMA_ENABLED=$(jq -r '.uptimekuma_enabled // false' "$CONFIG_PATH")
export UPTIMEKUMA_URL=$(jq -r '.uptimekuma_url // ""' "$CONFIG_PATH")
export UPTIMEKUMA_API_KEY=$(jq -r '.uptimekuma_api_key // ""' "$CONFIG_PATH")
export UPTIMEKUMA_STATUS_SLUG=$(jq -r '.uptimekuma_status_slug // ""' "$CONFIG_PATH")

# SMTP intake
export SMTP_ENABLED=$(jq -r '.smtp_enabled // false' "$CONFIG_PATH")
export SMTP_BIND=$(jq -r '.smtp_bind // "0.0.0.0"' "$CONFIG_PATH")
export SMTP_PORT=$(jq -r '.smtp_port // 2525' "$CONFIG_PATH")

# Proxy
export PROXY_ENABLED=$(jq -r '.proxy_enabled // false' "$CONFIG_PATH")
export PROXY_PORT=$(jq -r '.proxy_port // 2580' "$CONFIG_PATH")

# Push toggles
export push_gotify_enabled=$(jq -r '.push_gotify_enabled // false' "$CONFIG_PATH")
export push_ntfy_enabled=$(jq -r '.push_ntfy_enabled // false' "$CONFIG_PATH")

# === ADDITIVE FIX: Export NTFY and SMTP configs ===
export NTFY_URL=$(jq -r '.ntfy_url // ""' "$CONFIG_PATH")
export NTFY_TOPIC=$(jq -r '.ntfy_topic // "jarvis"' "$CONFIG_PATH")
export NTFY_USER=$(jq -r '.ntfy_user // ""' "$CONFIG_PATH")
export NTFY_PASS=$(jq -r '.ntfy_pass // ""' "$CONFIG_PATH")
export NTFY_TOKEN=$(jq -r '.ntfy_token // ""' "$CONFIG_PATH")

export push_smtp_enabled=$(jq -r '.push_smtp_enabled // false' "$CONFIG_PATH")
export push_smtp_host=$(jq -r '.push_smtp_host // ""' "$CONFIG_PATH")
export push_smtp_port=$(jq -r '.push_smtp_port // 587' "$CONFIG_PATH")
export push_smtp_user=$(jq -r '.push_smtp_user // ""' "$CONFIG_PATH")
export push_smtp_pass=$(jq -r '.push_smtp_pass // ""' "$CONFIG_PATH")
export push_smtp_to=$(jq -r '.push_smtp_to // ""' "$CONFIG_PATH")
# === END ADDITIVE FIX ===

# Personalities
export CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")

# ===== LLM controls =====
LLM_ENABLED=$(jq -r '.llm_enabled // false' "$CONFIG_PATH")
ENGINE="disabled"; LLM_STATUS="Disabled"; ACTIVE_PATH=""
if [ "$LLM_ENABLED" = "true" ]; then
  ENGINE="phi3"; LLM_STATUS="Phi-3"; ACTIVE_PATH="/share/jarvis_prime/models/phi3.gguf"
fi

# ===== RAG bootstrap =====
mkdir -p /share/jarvis_prime/memory /share/jarvis_prime || true
export RAG_REFRESH_SECONDS=$(jq -r '.rag_refresh_seconds // 900' "$CONFIG_PATH")
python3 /app/rag.py || true
(
  set +e
  while true; do
    sleep "${RAG_REFRESH_SECONDS}"
    python3 /app/rag.py || true
  done
) &

# ===== Banner =====
WS_ENABLED=$(jq -r '.intake_ws_enabled // false' "$CONFIG_PATH")
WS_PORT=$(jq -r '.intake_ws_port // 8765' "$CONFIG_PATH")
BANNER_LLM="$( [ "$LLM_ENABLED" = "true" ] && echo "$LLM_STATUS" || echo "Disabled" )"
BANNER_WS="$( [ "$WS_ENABLED" = "true" ] && echo "Enabled (port $WS_PORT)" || echo "Disabled" )"
banner "$BANNER_LLM" "$ENGINE" "${ACTIVE_PATH:-}" "$BANNER_WS"

# ===== Launch services =====
python3 /app/api_messages.py & API_PID=$!

if [[ "${SMTP_ENABLED}" == "true" ]]; then
  python3 /app/smtp_server.py & SMTP_PID=$! || true
fi

if [[ "${PROXY_ENABLED}" == "true" ]]; then
  python3 /app/proxy.py & PROXY_PID=$! || true
  # --- ADDITIVE: Forward envs persistently ---
  env \
    NTFY_URL="$NTFY_URL" \
    NTFY_TOPIC="$NTFY_TOPIC" \
    NTFY_USER="$NTFY_USER" \
    NTFY_PASS="$NTFY_PASS" \
    NTFY_TOKEN="$NTFY_TOKEN" \
    push_smtp_enabled="$push_smtp_enabled" \
    push_smtp_host="$push_smtp_host" \
    push_smtp_port="$push_smtp_port" \
    push_smtp_user="$push_smtp_user" \
    push_smtp_pass="$push_smtp_pass" \
    push_smtp_to="$push_smtp_to" \
    python3 /app/bot.py & BOT_PID=$! || true
  # --- END ADDITIVE ---
fi

if [[ "${WS_ENABLED}" == "true" ]]; then
  WS_TOKEN=$(jq -r '.intake_ws_token // "changeme"' "$CONFIG_PATH")
  WS_PORT=$WS_PORT WS_TOKEN=$WS_TOKEN python3 /app/websocket.py & WS_PID=$! || true
fi

wait "$API_PID"