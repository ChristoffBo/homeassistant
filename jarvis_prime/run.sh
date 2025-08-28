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
export BEAUTIFY_ENABLED=$(jq -r '.beautify_enabled // true' "$CONFIG_PATH")
export SILENT_REPOST=$(jq -r '.silent_repost // true' "$CONFIG_PATH")
export BEAUTIFY_INLINE_IMAGES=$(jq -r '.beautify_inline_images // false' "$CONFIG_PATH")

# Chat & Digest (file or env toggles)
export chat_enabled_file=$(jq -r '.chat_enabled // false' "$CONFIG_PATH")
export digest_enabled_file=$(jq -r '.digest_enabled // false' "$CONFIG_PATH")

# ARR & integrations
export radarr_enabled=$(jq -r '.radarr_enabled // false' "$CONFIG_PATH")
export sonarr_enabled=$(jq -r '.sonarr_enabled // false' "$CONFIG_PATH")
export weather_enabled=$(jq -r '.weather_enabled // false' "$CONFIG_PATH")
export technitium_enabled=$(jq -r '.technitium_enabled // false' "$CONFIG_PATH")
export uptimekuma_enabled=$(jq -r '.uptimekuma_enabled // false' "$CONFIG_PATH")

# SMTP intake
export smtp_enabled=$(jq -r '.smtp_enabled // true' "$CONFIG_PATH")
export smtp_bind=$(jq -r '.smtp_bind // "0.0.0.0"' "$CONFIG_PATH")
export smtp_port=$(jq -r '.smtp_port // 2525' "$CONFIG_PATH")
export smtp_accept_any_auth=$(jq -r '.smtp_accept_any_auth // true' "$CONFIG_PATH")
export smtp_dummy_rcpt=$(jq -r '.smtp_dummy_rcpt // "alerts@jarvis.local"' "$CONFIG_PATH")
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
export LLM_MODELS_PRIORITY=$(jq -r 'try (.llm_models_priority | join(",")) catch ""' "$CONFIG_PATH")

# ── Startup banner ────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────"
echo "🧠 ${BOT_NAME} ${BOT_ICON}"
echo "⚡ Boot sequence initiated..."
echo "   → Personalities loaded"
echo "   → Memory core mounted"
echo "   → Network bridges linked"
echo "──────────────────────────────────────────────"

# ── Prefetch Neural Core model (only when enabled) ────────────────────────────
if [ "$LLM_ENABLED" = "true" ]; then
  echo "[${BOT_NAME}] 🔮 Prefetching Neural Core model..."
  LLM_ENABLED=true \
  LLM_MODEL_URL="$LLM_MODEL_URL" \
  LLM_MODEL_PATH="$LLM_MODEL_PATH" \
  LLM_MODEL_SHA256="$LLM_MODEL_SHA256" \
  LLM_MODELS_PRIORITY="$LLM_MODELS_PRIORITY" \
  python3 /app/llm_client.py || true
  echo "[${BOT_NAME}] 🔮 Neural Core self-test fired."
fi

# ── Run the bot ───────────────────────────────────────────────────────────────
exec python3 /app/bot.py
