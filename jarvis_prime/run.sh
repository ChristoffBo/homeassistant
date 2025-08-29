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

# ========= CORE ENV (required by bot.py) =========
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
export technitium_enabled=$(jq -r '.technitium_enabled // false' "$CONFIG_PATH")
export technitium_url=$(jq -r '.technitium_url // ""' "$CONFIG_PATH")
export technitium_api_key=$(jq -r '.technitium_api_key // ""' "$CONFIG_PATH")
export technitium_user=$(jq -r '.technitium_user // ""' "$CONFIG_PATH")
export technitium_pass=$(jq -r '.technitium_pass // ""' "$CONFIG_PATH")

# Uptime Kuma
export uptimekuma_enabled=$(jq -r '.uptimekuma_enabled // false' "$CONFIG_PATH")
export uptimekuma_url=$(jq -r '.uptimekuma_url // ""' "$CONFIG_PATH")
export uptimekuma_api_key=$(jq -r '.uptimekuma_api_key // ""' "$CONFIG_PATH")
export uptimekuma_status_slug=$(jq -r '.uptimekuma_status_slug // ""' "$CONFIG_PATH")

# SMTP intake
export smtp_enabled=$(jq -r '.smtp_enabled // false' "$CONFIG_PATH")
export smtp_bind=$(jq -r '.smtp_bind // "0.0.0.0"' "$CONFIG_PATH")
export smtp_port=$(jq -r '.smtp_port // 2525' "$CONFIG_PATH")
export smtp_max_bytes=$(jq -r '.smtp_max_bytes // 262144' "$CONFIG_PATH")
export smtp_dummy_rcpt=$(jq -r '.smtp_dummy_rcpt // "alerts@jarvis.local"' "$CONFIG_PATH")
export smtp_accept_any_auth=$(jq -r '.smtp_accept_any_auth // true' "$CONFIG_PATH")
export smtp_rewrite_title_prefix=$(jq -r '.smtp_rewrite_title_prefix // "[SMTP]"' "$CONFIG_PATH")
export smtp_allow_html=$(jq -r '.smtp_allow_html // false' "$CONFIG_PATH")
export smtp_priority_default=$(jq -r '.smtp_priority_default // 5' "$CONFIG_PATH")
export smtp_priority_map=$(jq -r '.smtp_priority_map // "{}"' "$CONFIG_PATH")

# Proxy
export proxy_enabled=$(jq -r '.proxy_enabled // false' "$CONFIG_PATH")
export proxy_bind=$(jq -r '.proxy_bind // "0.0.0.0"' "$CONFIG_PATH")
export proxy_port=$(jq -r '.proxy_port // 2580' "$CONFIG_PATH")
export proxy_gotify_url=$(jq -r '.proxy_gotify_url // ""' "$CONFIG_PATH")
export proxy_ntfy_url=$(jq -r '.proxy_ntfy_url // ""' "$CONFIG_PATH")

# Personality
export CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")

# ========= LLM per-model toggles =========
LLM_ENABLED=$(jq -r '.llm_enabled // false' "$CONFIG_PATH")
CLEANUP=$(jq -r '.llm_cleanup_on_disable // true' "$CONFIG_PATH")
MODELS_DIR=$(jq -r '.llm_models_dir // "/share/jarvis_prime/models"' "$CONFIG_PATH")
mkdir -p "$MODELS_DIR" || true

PHI_ON=$(jq -r '.llm_phi3_enabled // false' "$CONFIG_PATH")
TINY_ON=$(jq -r '.llm_tinyllama_enabled // false' "$CONFIG_PATH")
QWEN_ON=$(jq -r '.llm_qwen05_enabled // false' "$CONFIG_PATH")

PHI_URL=$(jq -r '.llm_phi3_url // ""' "$CONFIG_PATH");  PHI_PATH=$(jq -r '.llm_phi3_path // ""' "$CONFIG_PATH")
TINY_URL=$(jq -r '.llm_tinyllama_url // ""' "$CONFIG_PATH"); TINY_PATH=$(jq -r '.llm_tinyllama_path // ""' "$CONFIG_PATH")
QWEN_URL=$(jq -r '.llm_qwen05_url // ""' "$CONFIG_PATH");  QWEN_PATH=$(jq -r '.llm_qwen05_path // ""' "$CONFIG_PATH")

# defaults for LLM env
export LLM_MODEL_PATH=""
export LLM_MODEL_URLS=""
export LLM_MODEL_URL=""
export LLM_ENABLED

# Cleanup when toggled off
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
  if   [ "$PHI_ON"  = "true" ]; then ENGINE="phi3";      ACTIVE_PATH="$PHI_PATH";  ACTIVE_URL="$PHI_URL";
  elif [ "$TINY_ON" = "true" ]; then ENGINE="tinyllama"; ACTIVE_PATH="$TINY_PATH"; ACTIVE_URL="$TINY_URL";
  elif [ "$QWEN_ON" = "true" ]; then ENGINE="qwen05";    ACTIVE_PATH="$QWEN_PATH"; ACTIVE_URL="$QWEN_URL";
  else ENGINE="none-selected"; fi

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

banner "$( [ "$LLM_ENABLED" = "true" ] && echo 'enabled' || echo 'disabled' )" "$ENGINE" "$ACTIVE_PATH"

# Hand off to bot
exec python3 /app/bot.py
