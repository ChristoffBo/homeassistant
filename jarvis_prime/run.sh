#!/usr/bin/env bash
set -Eeuo pipefail

# --- Jarvis Prime bootstrap ---
SHARE_DIR="/share/jarvis_prime"
MEM_DIR="$SHARE_DIR/memory"
MODEL_DIR="$SHARE_DIR/models"
OPTS="/data/options.json"

# Ensure shared folders exist
mkdir -p "$MEM_DIR" "$MODEL_DIR"

# Seed system prompt to host share on first run (so it can be edited without rebuilds)
if [ ! -s "$MEM_DIR/system_prompt.txt" ] && [ -f "/app/memory/system_prompt.txt" ]; then
  cp -f "/app/memory/system_prompt.txt" "$MEM_DIR/system_prompt.txt"
  echo "[Jarvis Prime] Seeded system prompt -> $MEM_DIR/system_prompt.txt"
fi

# Helper to read a key from options.json safely
jqget() {
  local key="$1"
  jq -r "try ${key} // empty" "$OPTS" 2>/dev/null || true
}

# ---- Export LLM controls from add-on options ----
# Context window (prompt/system/history headroom). Default 4096.
LLM_CTX_TOKENS="$(jqget '.llm_ctx_tokens')"
[ -z "$LLM_CTX_TOKENS" ] && LLM_CTX_TOKENS="4096"
export LLM_CTX_TOKENS

# Max tokens to generate each response (short to keep latency). Default 180.
LLM_GEN_TOKENS="$(jqget '.llm_gen_tokens')"
[ -z "$LLM_GEN_TOKENS" ] && LLM_GEN_TOKENS="180"
export LLM_GEN_TOKENS

# Max lines in final post-beautified output. Default 10.
LLM_MAX_LINES="$(jqget '.llm_max_lines')"
[ -z "$LLM_MAX_LINES" ] && LLM_MAX_LINES="10"
export LLM_MAX_LINES

# Optional: inline system prompt override (falls back to /share/jarvis_prime/memory/system_prompt.txt or /app/memory/system_prompt.txt)
LLM_SYSTEM_PROMPT="$(jqget '.llm_system_prompt')"
[ -n "$LLM_SYSTEM_PROMPT" ] && export LLM_SYSTEM_PROMPT

# Optional: model family preference order (lower is preferred). Default "phi,qwen,tinyllama".
LLM_MODEL_PREFERENCE="$(jqget '.llm_model_preference')"
[ -n "$LLM_MODEL_PREFERENCE" ] && export LLM_MODEL_PREFERENCE

# Optional: Ollama base URL if you want to use a remote/local Ollama server instead of ctransformers.
OLLAMA_BASE_URL="$(jqget '.llm_ollama_base_url')"
[ -n "$OLLAMA_BASE_URL" ] && export OLLAMA_BASE_URL

# Hand off to the bot
exec python3 /app/bot.py
