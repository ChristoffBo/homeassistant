#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json

# Ensure models & memory dirs exist
MODELS_DIR=$(jq -r '.llm_models_dir // "/share/jarvis_prime/models"' "$CONFIG_PATH")
MEMORY_DIR="/share/jarvis_prime/memory"
mkdir -p "$MODELS_DIR" || true
mkdir -p "$MEMORY_DIR" || true

# Seed default memory files if missing (no manual copying required)
if [ ! -f "$MEMORY_DIR/flashcards.txt" ]; then
  cat > "$MEMORY_DIR/flashcards.txt" <<'FLASH'
=== JARVIS PRIME — FLASHCARD TRAINING PACK (bootstrapped) ===
Use the strict shapes; never add commentary. If unknown, use "unknown".
[Generic]
❓ Generic: unknown message content. Ignored.
FLASH
fi
if [ ! -f "$MEMORY_DIR/system_prompt.txt" ]; then
  cat > "$MEMORY_DIR/system_prompt.txt" <<'SP'
You are Jarvis Prime. Keep outputs concise and structured. Never fabricate data.
When rewriting logs, prefer the flashcard patterns in /share/jarvis_prime/memory/flashcards.txt.
If the message is not a log, return the Generic shape described in the flashcards.
SP
fi

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

# LLM (built-in)
LLM_ENABLED=$(jq -r '.llm_enabled // false' "$CONFIG_PATH")
LLM_MODEL_URL=$(jq -r '.llm_model_url // ""' "$CONFIG_PATH")
LLM_MODEL_PATH=$(jq -r '.llm_model_path // ""' "$CONFIG_PATH")
LLM_MODEL_SHA=$(jq -r '.llm_model_sha256 // ""' "$CONFIG_PATH")
CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")

# --- NEW: LLM controls exposed via add-on options (with safe defaults)
export LLM_CTX_TOKENS=$(jq -r '.llm_ctx_tokens // 4096' "$CONFIG_PATH")
export LLM_GEN_TOKENS=$(jq -r '.llm_gen_tokens // 180' "$CONFIG_PATH")
export LLM_MAX_LINES=$(jq -r '.llm_max_lines // 10' "$CONFIG_PATH")
export LLM_SYSTEM_PROMPT=$(jq -r '.llm_system_prompt // ""' "$CONFIG_PATH")
export LLM_MODEL_PREFERENCE=$(jq -r '.llm_model_preference // "phi,qwen,tinyllama"' "$CONFIG_PATH")
export OLLAMA_BASE_URL=$(jq -r '.llm_ollama_base_url // ""' "$CONFIG_PATH")

# Per-model toggles and URLs/paths
PHI_ON=$(jq -r '.llm_phi3_enabled // false' "$CONFIG_PATH")
TINY_ON=$(jq -r '.llm_tinyllama_enabled // false' "$CONFIG_PATH")
QWEN_ON=$(jq -r '.llm_qwen05_enabled // false' "$CONFIG_PATH")

PHI_URL=$(jq -r '.llm_phi3_url // ""' "$CONFIG_PATH");    PHI_PATH=$(jq -r '.llm_phi3_path // ""' "$CONFIG_PATH")
TINY_URL=$(jq -r '.llm_tinyllama_url // ""' "$CONFIG_PATH"); TINY_PATH=$(jq -r '.llm_tinyllama_path // ""' "$CONFIG_PATH")
QWEN_URL=$(jq -r '.llm_qwen05_url // ""' "$CONFIG_PATH");  QWEN_PATH=$(jq -r '.llm_qwen05_path // ""' "$CONFIG_PATH")

# Default filenames if paths are empty
[ -z "$PHI_PATH"  ]  && PHI_PATH="$MODELS_DIR/Phi-3-mini-4k-instruct-q4.gguf"
[ -z "$TINY_PATH" ]  && TINY_PATH="$MODELS_DIR/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"
[ -z "$QWEN_PATH" ]  && QWEN_PATH="$MODELS_DIR/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"

_active_path=""; _active_url=""
if [ "$LLM_ENABLED" = "true" ]; then
  if   [ "$PHI_ON" = "true" ]; then _active_path="$PHI_PATH"; _active_url="$PHI_URL";
  elif [ "$TINY_ON" = "true" ]; then _active_path="$TINY_PATH"; _active_url="$TINY_URL";
  elif [ "$QWEN_ON" = "true" ]; then _active_path="$QWEN_PATH"; _active_url="$QWEN_URL";
  fi
  # Download if URL provided and file missing
  if [ -n "$_active_url" ] && [ ! -s "$_active_path" ]; then
    echo "[Jarvis Prime] 🔮 Downloading model to $_active_path"
    mkdir -p "$(dirname "$_active_path")" || true
    curl -L --fail --retry 3 -o "$_active_path" "$_active_url" || true
  fi
  if [ -s "$_active_path" ]; then
    export LLM_MODEL_PATH="$_active_path"
  fi
fi


# -----------------------------
# Startup banner
# -----------------------------
echo "──────────────────────────────────────────────"
echo "🧠 ${BOT_NAME} ${BOT_ICON}"
echo "⚡ Boot sequence initiated..."
echo "   → Personalities loaded"
echo "   → Memory core mounted"
echo "   → Network bridges linked"
echo "   → LLM: $( [ "$LLM_ENABLED" = "true" ] && echo "enabled" || echo "disabled" )"
echo "🚀 Systems online — Jarvis is awake!"
echo "──────────────────────────────────────────────"

# Ensure share directories exist
mkdir -p /share/jarvis_prime/memory
if [ -n "$LLM_MODEL_PATH" ]; then
  mkdir -p "$(dirname "$LLM_MODEL_PATH")"
fi

# Seed default system prompt to /share so you can edit without rebuilding
if [ ! -s /share/jarvis_prime/memory/system_prompt.txt ] && [ -f /app/memory/system_prompt.txt ]; then
  cp -f /app/memory/system_prompt.txt /share/jarvis_prime/memory/system_prompt.txt
  echo "[${BOT_NAME}] Seeded system prompt -> /share/jarvis_prime/memory/system_prompt.txt"
fi

# Prefetch once on startup so the model downloads immediately (or warms up)
if [ "$LLM_ENABLED" = "true" ] && [ -n "$LLM_MODEL_URL" ] && [ -n "$LLM_MODEL_PATH" ]; then
  echo "[${BOT_NAME}] 🔮 Prefetching LLM model..."
  python3 - <<'PY'
import json, os
cfg = json.load(open("/data/options.json"))
try:
    from llm_client import rewrite
    out = rewrite(
        text="(prefetch)",
        mood=cfg.get("personality_mood","serious"),
        timeout=int(cfg.get("llm_timeout_seconds",5)),
        cpu_limit=int(cfg.get("llm_max_cpu_percent",70)),
        models_priority=[],
        base_url=cfg.get("llm_ollama_base_url",""),
        model_url=cfg.get("llm_model_url",""),
        model_path=cfg.get("llm_model_path",""),
        model_sha256=cfg.get("llm_model_sha256","")
    )
    print("[Jarvis Prime] 🧠 Prefetch complete")
except Exception as e:
    print(f"[Jarvis Prime] ⚠️ Prefetch failed: {e}")
PY
fi

# Start the bot
exec python3 /app/bot.py
