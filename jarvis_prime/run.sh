#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json

# -------- helpers --------
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

py_download() {
python3 - "$1" "$2" <<'PY'
import sys, os, urllib.request, shutil, tempfile, pathlib
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

# -------- read options --------
LLM_ENABLED=$(jq -r '.llm_enabled // false' "$CONFIG_PATH")
CLEANUP=$(jq -r '.llm_cleanup_on_disable // true' "$CONFIG_PATH")
MODELS_DIR=$(jq -r '.llm_models_dir // "/share/jarvis_prime/models"' "$CONFIG_PATH")

PHI_ON=$(jq -r '.llm_phi3_enabled // false' "$CONFIG_PATH")
TINY_ON=$(jq -r '.llm_tinyllama_enabled // false' "$CONFIG_PATH")
QWEN_ON=$(jq -r '.llm_qwen05_enabled // false' "$CONFIG_PATH")

PHI_URL=$(jq -r '.llm_phi3_url // ""' "$CONFIG_PATH")
PHI_PATH=$(jq -r '.llm_phi3_path // ""' "$CONFIG_PATH")
TINY_URL=$(jq -r '.llm_tinyllama_url // ""' "$CONFIG_PATH")
TINY_PATH=$(jq -r '.llm_tinyllama_path // ""' "$CONFIG_PATH")
QWEN_URL=$(jq -r '.llm_qwen05_url // ""' "$CONFIG_PATH")
QWEN_PATH=$(jq -r '.llm_qwen05_path // ""' "$CONFIG_PATH")

# Defaults for env
export LLM_MODEL_PATH=""
export LLM_MODEL_URLS=""
export LLM_MODEL_URL=""
export LLM_ENABLED

# Cleanup logic per model when toggled off
if [ "$CLEANUP" = "true" ]; then
  if [ "$LLM_ENABLED" = "false" ]; then
    rm -f "$PHI_PATH" "$TINY_PATH" "$QWEN_PATH" || true
  else
    if [ "$PHI_ON" = "false" ] && [ -f "$PHI_PATH" ]; then rm -f "$PHI_PATH" || true; fi
    if [ "$TINY_ON" = "false" ] && [ -f "$TINY_PATH" ]; then rm -f "$TINY_PATH" || true; fi
    if [ "$QWEN_ON" = "false" ] && [ -f "$QWEN_PATH" ]; then rm -f "$QWEN_PATH" || true; fi
  fi
fi

ENGINE="disabled"
ACTIVE_PATH=""
ACTIVE_URL=""

if [ "$LLM_ENABLED" = "true" ]; then
  # priority: phi3 > tinyllama > qwen05
  if [ "$PHI_ON" = "true" ]; then
    ENGINE="phi3"
    ACTIVE_PATH="$PHI_PATH"
    ACTIVE_URL="$PHI_URL"
  elif [ "$TINY_ON" = "true" ]; then
    ENGINE="tinyllama"
    ACTIVE_PATH="$TINY_PATH"
    ACTIVE_URL="$TINY_URL"
  elif [ "$QWEN_ON" = "true" ]; then
    ENGINE="qwen05"
    ACTIVE_PATH="$QWEN_PATH"
    ACTIVE_URL="$QWEN_URL"
  else
    ENGINE="none-selected"
  fi

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

banner "$( [ "$LLM_ENABLED" = "true" ] && echo "enabled" || echo "disabled" )" "$ENGINE" "$ACTIVE_PATH"

# Expose other tuning env (read-only if missing)
export LLM_CTX_TOKENS=$(jq -r '.llm_ctx_tokens // 1024' "$CONFIG_PATH")
export LLM_GEN_TOKENS=$(jq -r '.llm_gen_tokens // 256' "$CONFIG_PATH")
export LLM_MAX_LINES=$(jq -r '.llm_max_lines // 10' "$CONFIG_PATH")
export LLM_SYSTEM_PROMPT=$(jq -r '.llm_system_prompt // ""' "$CONFIG_PATH")
export CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")

# Hand off to bot
exec python3 /app/bot.py
