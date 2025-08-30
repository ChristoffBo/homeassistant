#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json

# -------- helper: banner --------
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
  echo "🚀 Systems online — Jarvis is awake!"
  echo "──────────────────────────────────────────────"
}

# -------- helper: simple Python downloader --------
py_download() {
python3 - "$1" "$2" <<'PY'
import sys, os, urllib.request, shutil, pathlib
url, dst = sys.argv[1], sys.argv[2]
path = pathlib.Path(dst)
path.parent.mkdir(parents=True, exist_ok=True)
tmp = str(path)+".part"
try:
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=1024*1024)
    os.replace(tmp, dst)
    print(f"[Downloader] Fetched -> {dst}")
except Exception as e:
    try:
        if os.path.exists(tmp): os.remove(tmp)
    except: pass
    print(f"[Downloader] Failed: {e}")
    sys.exit(1)
PY
}

# ========= CORE ENV (required by modules) =========
# Basic
export BOT_NAME=$(jq -r '.bot_name' "$CONFIG_PATH")
export BOT_ICON=$(jq -r '.bot_icon' "$CONFIG_PATH")
export GOTIFY_URL=$(jq -r '.gotify_url' "$CONFIG_PATH")
export GOTIFY_CLIENT_TOKEN=$(jq -r '.gotify_client_token' "$CONFIG_PATH")
export GOTIFY_APP_TOKEN=$(jq -r '.gotify_app_token' "$CONFIG_PATH")
export JARVIS_APP_NAME=$(jq -r '.jarvis_app_name' "$CONFIG_PATH")

# Inbox / retention
export RETENTION_HOURS=$(jq -r '.retention_hours' "$CONFIG_PATH")
export INBOX_RETENTION_DAYS=$(jq -r '.retention_days // 30' "$CONFIG_PATH")
export AUTO_PURGE_POLICY=$(jq -r '.auto_purge_policy // "off"' "$CONFIG_PATH")

# Feature toggles
export BEAUTIFY_ENABLED=$(jq -r '.beautify_enabled' "$CONFIG_PATH")
export SILENT_REPOST=$(jq -r '.silent_repost // "true"' "$CONFIG_PATH")

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

# Personalities / mood
export CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")

# Ingest toggles (informational for logs; mirrors run when URLs are provided)
export INGEST_GOTIFY_ENABLED=$(jq -r '.ingest_gotify_enabled // true' "$CONFIG_PATH")
export INGEST_NTFY_ENABLED=$(jq -r '.ingest_ntfy_enabled // false' "$CONFIG_PATH")
export INGEST_SMTP_ENABLED=$(jq -r '.ingest_smtp_enabled // true' "$CONFIG_PATH")

# Push toggles
export PUSH_GOTIFY_ENABLED=$(jq -r '.push_gotify_enabled // true' "$CONFIG_PATH")
export PUSH_NTFY_ENABLED=$(jq -r '.push_ntfy_enabled // false' "$CONFIG_PATH")
export PUSH_SMTP_ENABLED=$(jq -r '.push_smtp_enabled // false' "$CONFIG_PATH")
export PUSH_SMTP_HOST=$(jq -r '.push_smtp_host // "smtp.gmail.com"' "$CONFIG_PATH")
export PUSH_SMTP_PORT=$(jq -r '.push_smtp_port // 587' "$CONFIG_PATH")
export PUSH_SMTP_USER=$(jq -r '.push_smtp_user // ""' "$CONFIG_PATH")
export PUSH_SMTP_PASS=$(jq -r '.push_smtp_pass // ""' "$CONFIG_PATH")
export PUSH_SMTP_TO=$(jq -r '.push_smtp_to // ""' "$CONFIG_PATH")

# NTFY for inbox mirror & push
export NTFY_URL=$(jq -r '.ntfy_url // ""' "$CONFIG_PATH")
export NTFY_TOPIC=$(jq -r '.ntfy_topic // ""' "$CONFIG_PATH")
export NTFY_USER=$(jq -r '.ntfy_user // ""' "$CONFIG_PATH")
export NTFY_PASS=$(jq -r '.ntfy_pass // ""' "$CONFIG_PATH")
export NTFY_TOKEN=$(jq -r '.ntfy_token // ""' "$CONFIG_PATH")

# ========= LLM controls =========
LLM_ENABLED=$(jq -r '.llm_enabled // false' "$CONFIG_PATH")
CLEANUP=$(jq -r '.llm_cleanup_on_disable // true' "$CONFIG_PATH")
MODELS_DIR=$(jq -r '.llm_models_dir // "/share/jarvis_prime/models"' "$CONFIG_PATH")
mkdir -p "$MODELS_DIR" || true

export LLM_TIMEOUT_SECONDS=$(jq -r '.llm_timeout_seconds // 8' "$CONFIG_PATH")
export LLM_MAX_CPU_PERCENT=$(jq -r '.llm_max_cpu_percent // 70' "$CONFIG_PATH")

PHI_ON=$(jq -r '.llm_phi3_enabled // false' "$CONFIG_PATH")
TINY_ON=$(jq -r '.llm_tinyllama_enabled // false' "$CONFIG_PATH")
QWEN_ON=$(jq -r '.llm_qwen05_enabled // false' "$CONFIG_PATH")

PHI_URL=$(jq -r '.llm_phi3_url // ""' "$CONFIG_PATH");  PHI_PATH=$(jq -r '.llm_phi3_path // ""' "$CONFIG_PATH")
TINY_URL=$(jq -r '.llm_tinyllama_url // ""' "$CONFIG_PATH"); TINY_PATH=$(jq -r '.llm_tinyllama_path // ""' "$CONFIG_PATH")
QWEN_URL=$(jq -r '.llm_qwen05_url // ""' "$CONFIG_PATH");  QWEN_PATH=$(jq -r '.llm_qwen05_path // ""' "$CONFIG_PATH")

export LLM_MODEL_PATH=""
export LLM_MODEL_URLS=""
export LLM_MODEL_URL=""
export LLM_ENABLED
export LLM_STATUS="Disabled"

if [ "$CLEANUP" = "true" ]; then
  if [ "$LLM_ENABLED" = "false" ]; then
    rm -f "$PHI_PATH" "$TINY_PATH" "$QWEN_PATH" || true
  else
    [ "$PHI_ON"  = "false" ] && [ -f "$PHI_PATH" ]  && rm -f "$PHI_PATH"  || true
    [ "$TINY_ON" = "false" ] && [ -f "$TINY_PATH" ] && rm -f "$TINY_PATH" || true
    [ "$QWEN_ON" = "false" ] && [ -f "$QWEN_PATH" ] && rm -f "$QWEN_PATH" || true
  fi
fi

ENGINE="disabled"; ACTIVE_PATH=""; ACTIVE_URL=""
if [ "$LLM_ENABLED" = "true" ]; then
  COUNT=0
  [ "$PHI_ON"  = "true" ] && COUNT=$((COUNT+1))
  [ "$TINY_ON" = "true" ] && COUNT=$((COUNT+1))
  [ "$QWEN_ON" = "true" ] && COUNT=$((COUNT+1))
  if [ "$COUNT" -gt 1 ]; then
    echo "[Jarvis Prime] ⚠️ Multiple models enabled; using first true (phi3→tinyllama→qwen05)."
  fi
  if   [ "$PHI_ON"  = "true" ]; then ENGINE="phi3";      ACTIVE_PATH="$PHI_PATH";  ACTIVE_URL="$PHI_URL";  LLM_STATUS="Phi‑3";
  elif [ "$TINY_ON" = "true" ]; then ENGINE="tinyllama"; ACTIVE_PATH="$TINY_PATH"; ACTIVE_URL="$TINY_URL"; LLM_STATUS="TinyLlama";
  elif [ "$QWEN_ON" = "true" ]; then ENGINE="qwen05";    ACTIVE_PATH="$QWEN_PATH"; ACTIVE_URL="$QWEN_URL"; LLM_STATUS="Qwen‑0.5b";
  else ENGINE="none-selected"; LLM_STATUS="Disabled"; fi

  if [ -n "$ACTIVE_URL" ] && [ -n "$ACTIVE_PATH" ]; then
    if [ ! -s "$ACTIVE_PATH" ]; then
      echo "[Jarvis Prime] 🔮 Downloading model ($ENGINE)…"
      py_download "$ACTIVE_URL" "$ACTIVE_PATH"
    fi
    if [ -s "$ACTIVE_PATH" ]; then
      export LLM_MODEL_PATH="$ACTIVE_PATH"
      export LLM_MODEL_URL="$ACTIVE_URL"
      export LLM_MODEL_URLS="$ACTIVE_URL"
    fi
  fi
fi

# Guard against empty Gotify settings (prevent reconnect loop)
if [ -z "${GOTIFY_URL:-}" ] || [ -z "${GOTIFY_CLIENT_TOKEN:-}" ]; then
  echo "[Jarvis Prime] ❌ Missing gotify_url or gotify_client_token in options.json — aborting."
  exit 1
fi

# ===== Inbox service (API + UI) =====
export JARVIS_API_BIND="0.0.0.0"
export JARVIS_API_PORT="2581"
export JARVIS_DB_PATH="/data/jarvis.db"
export JARVIS_UI_DIR="/app/ui"
mkdir -p "$JARVIS_UI_DIR" || true

BANNER_LLM="$( [ "$LLM_ENABLED" = "true" ] && echo "$LLM_STATUS" || echo "Disabled" )"
banner "$BANNER_LLM" "$ENGINE" "${LLM_MODEL_PATH:-}"

echo "[launcher] URLs: gotify=$GOTIFY_URL ntfy=${NTFY_URL:-}"
echo "[launcher] starting inbox server (api_messages.py) on :$JARVIS_API_PORT"
python3 /app/api_messages.py &
API_PID=$!

# ===== SMTP intake =====
if [[ "${SMTP_ENABLED}" == "true" ]]; then
  echo "[launcher] starting SMTP intake (smtp_server.py) on ${SMTP_BIND}:${SMTP_PORT}"
  python3 /app/smtp_server.py &
  SMTP_PID=$!
else
  echo "[launcher] SMTP disabled"
fi

# ===== Proxy + Bot =====
if [[ "${PROXY_ENABLED}" == "true" ]]; then
  echo "[launcher] starting proxy (proxy.py)"
  python3 /app/proxy.py &
  PROXY_PID=$!
  echo "[launcher] starting bot (bot.py)"
  python3 /app/bot.py &
  BOT_PID=$!
else
  echo "[launcher] proxy disabled"
fi

# ===== Wait on children =====
wait "$API_PID"
