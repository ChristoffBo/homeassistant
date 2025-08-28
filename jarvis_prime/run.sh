#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json

# Small logger
log() {
  local bot
  bot="$(jq -r '.bot_name' "$CONFIG_PATH" 2>/dev/null || echo 'Jarvis Prime')"
  echo "[$bot] $*"
}

# -------- Core options exported in UPPERCASE (what Python expects) --------
export BOT_NAME="$(jq -r '.bot_name' "$CONFIG_PATH")"
export BOT_ICON="$(jq -r '.bot_icon' "$CONFIG_PATH")"
export GOTIFY_URL="$(jq -r '.gotify_url' "$CONFIG_PATH")"
export GOTIFY_CLIENT_TOKEN="$(jq -r '.gotify_client_token' "$CONFIG_PATH")"
export GOTIFY_APP_TOKEN="$(jq -r '.gotify_app_token' "$CONFIG_PATH")"
export JARVIS_APP_NAME="$(jq -r '.jarvis_app_name' "$CONFIG_PATH")"

export RETENTION_HOURS="$(jq -r '.retention_hours' "$CONFIG_PATH")"
export BEAUTIFY_ENABLED="$(jq -r '.beautify_enabled' "$CONFIG_PATH")"
export SILENT_REPOST="$(jq -r '.silent_repost // "true"' "$CONFIG_PATH")"

# Feature toggles shown on boot card
export RADARR_ENABLED="$(jq -r '.radarr_enabled' "$CONFIG_PATH")"
export SONARR_ENABLED="$(jq -r '.sonarr_enabled' "$CONFIG_PATH")"
export WEATHER_ENABLED="$(jq -r '.weather_enabled' "$CONFIG_PATH")"
export uptimekuma_enabled="$(jq -r '.uptimekuma_enabled' "$CONFIG_PATH")"
export smtp_enabled="$(jq -r '.smtp_enabled' "$CONFIG_PATH")"
export proxy_enabled="$(jq -r '.proxy_enabled' "$CONFIG_PATH")"
export technitium_enabled="$(jq -r '.technitium_enabled' "$CONFIG_PATH")"

# Personality / memory
export personality_mood="$(jq -r '.personality_mood' "$CONFIG_PATH")"
export PERSONALITY_PERSISTENT="$(jq -r '.personality_persistent' "$CONFIG_PATH")"

# ------------------------------ Neural Core -------------------------------
export LLM_ENABLED="$(jq -r '.llm_enabled' "$CONFIG_PATH")"
export LLM_MEMORY_ENABLED="$(jq -r '.llm_memory_enabled' "$CONFIG_PATH")"
export LLM_TIMEOUT_SECONDS="$(jq -r '.llm_timeout_seconds' "$CONFIG_PATH")"
export LLM_MAX_CPU_PERCENT="$(jq -r '.llm_max_cpu_percent' "$CONFIG_PATH")"
export LLM_MODEL_URL="$(jq -r '.llm_model_url // ""' "$CONFIG_PATH")"
export LLM_MODEL_PATH="$(jq -r '.llm_model_path // "/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf"' "$CONFIG_PATH")"
export LLM_MODEL_SHA256="$(jq -r '.llm_model_sha256 // ""' "$CONFIG_PATH")"

# ------------------------------- Directories ------------------------------
mkdir -p /share/jarvis_prime/memory
mkdir -p "$(dirname "$LLM_MODEL_PATH")"

# ---------------------------- Model prefetch ------------------------------
# Only if LLM is on AND file is missing AND we have a URL.
if [[ "${LLM_ENABLED,,}" == "true" ]]; then
  if [[ ! -s "$LLM_MODEL_PATH" ]]; then
    if [[ -n "$LLM_MODEL_URL" ]]; then
      log "🔮 Prefetching model → $LLM_MODEL_PATH"
      if ! python3 /app/llm_client.py; then
        log "⚠️ Prefetch failed (will boot with Beautifier fallback)."
      fi
    else
      log "⚠️ LLM_MODEL_URL not set; cannot prefetch."
    fi
  else
    log "🧠 Model present: $LLM_MODEL_PATH"
    ls -lh "$LLM_MODEL_PATH" || true
  fi
fi

# Show pipeline summary right in the add-on log
if [[ "${LLM_ENABLED,,}" == "true" ]]; then
  if [[ -s "$LLM_MODEL_PATH" ]]; then
    log "Pipeline: LLM ➜ polish (model present)"
  else
    log "Pipeline: LLM ➜ polish (model MISSING) — UI will still run, LLM skipped"
  fi
else
  log "Pipeline: Beautifier full pipeline (LLM disabled)"
fi

# ------------------------------ Start the bot -----------------------------
exec python3 /app/bot.py
