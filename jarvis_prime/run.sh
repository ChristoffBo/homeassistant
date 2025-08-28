#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json
log() { echo "[$(jq -r '.bot_name' "$CONFIG_PATH")] $*"; }

# ── Read options → environment ────────────────────────────────────────────────
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
export WEATHER_LAT=$(jq -r '.weather_lat // empty' "$CONFIG_PATH")
export WEATHER_LON=$(jq -r '.weather_lon // empty' "$CONFIG_PATH")

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

# Personality & Neural Core (LLM)
export CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")
export LLM_ENABLED=$(jq -r '.llm_enabled // false' "$CONFIG_PATH")
export LLM_MEMORY_ENABLED=$(jq -r '.llm_memory_enabled // false' "$CONFIG_PATH")
export PERSONALITY_PERSISTENT=$(jq -r '.personality_persistent // true' "$CONFIG_PATH")
export LLM_TIMEOUT_SECONDS=$(jq -r '.llm_timeout_seconds // 5' "$CONFIG_PATH")
export LLM_MAX_CPU_PERCENT=$(jq -r '.llm_max_cpu_percent // 70' "$CONFIG_PATH")
export LLM_MODEL_URL=$(jq -r '.llm_model_url // ""' "$CONFIG_PATH")
export LLM_MODEL_PATH=$(jq -r '.llm_model_path // ""' "$CONFIG_PATH")
export LLM_MODEL_SHA256=$(jq -r '.llm_model_sha256 // ""' "$CONFIG_PATH")
export LLM_MODELS_PRIORITY=$(jq -r 'try .llm_models_priority | join(",") catch ""' "$CONFIG_PATH")

# ── Startup banner ────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────"
echo "🧠 ${BOT_NAME} ${BOT_ICON}"
echo "⚡ Boot sequence initiated..."
echo "   → Personalities loaded"
echo "   → Memory core mounted"
echo "   → Network bridges linked"
echo "   → Neural Core: $( [ "$LLM_ENABLED" = "true" ] && echo "enabled" || echo "disabled" )"
echo "   → Model path: ${LLM_MODEL_PATH}"
echo "🚀 Systems online — Jarvis is awake!"
echo "──────────────────────────────────────────────"

# ── Ensure /share directories ─────────────────────────────────────────────────
mkdir -p /share/jarvis_prime/memory
if [ -n "$LLM_MODEL_PATH" ]; then
  mkdir -p "$(dirname "$LLM_MODEL_PATH")"
fi

# ── Seed the 24h memory with a boot event (creates events.json immediately) ──
if [ "$LLM_MEMORY_ENABLED" = "true" ]; then
  python3 - <<'PY'
import json, time, os
from pathlib import Path
MEMDIR = Path("/share/jarvis_prime/memory")
MEMDIR.mkdir(parents=True, exist_ok=True)
EV = MEMDIR / "events.json"
if not EV.exists():
    EV.write_text("[]", encoding="utf-8")
try:
    data = json.loads(EV.read_text(encoding="utf-8"))
except Exception:
    data = []
data.append({
    "ts": int(time.time()),
    "title": "Jarvis boot",
    "source": "system",
    "body": "Startup sequence completed",
    "tags": ["boot","system"]
})
# prune >24h
cut = int(time.time()) - 24*3600
data = [e for e in data if isinstance(e, dict) and e.get("ts",0) >= cut]
EV.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("[Jarvis Prime] 🗃️ Memory seeded at /share/jarvis_prime/memory/events.json")
PY
fi

# ── Prefetch Neural Core model (only when enabled) ────────────────────────────
if [ "$LLM_ENABLED" = "true" ]; then
  echo "[${BOT_NAME}] 🔮 Prefetching Neural Core model..."
  LLM_ENABLED=true \
  LLM_MODEL_URL="$LLM_MODEL_URL" \
  LLM_MODEL_PATH="$LLM_MODEL_PATH" \
  LLM_MODEL_SHA256="$LLM_MODEL_SHA256" \
  LLM_MODELS_PRIORITY="$LLM_MODELS_PRIORITY" \
  python3 /app/llm_client.py || true
fi

# ── Run the bot ───────────────────────────────────────────────────────────────
exec python3 /app/bot.py
