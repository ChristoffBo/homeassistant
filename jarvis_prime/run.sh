#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json

log() { echo "[Jarvis Prime] $*"; }

# read a field from options.json with jq or default
getoptj() { jq -r "$1 // empty" "$CONFIG_PATH" 2>/dev/null || true; }

# --- Read user options
MODELS_DIR="$(getoptj '.ollama_models_dir')"
[ -z "$MODELS_DIR" ] && MODELS_DIR="$(getoptj '.llm_models_dir')"
[ -z "$MODELS_DIR" ] && MODELS_DIR="/share/jarvis_prime/models"

PHI3_ON=$(getoptj '.llm_phi3_enabled');      [ "$PHI3_ON" = "true" ] || PHI3_ON="false"
PHI2_ON=$(getoptj '.llm_phi2_enabled');      [ "$PHI2_ON" = "true" ] || PHI2_ON="false"
GEMMA2_ON=$(getoptj '.llm_gemma2_enabled');  [ "$GEMMA2_ON" = "true" ] || GEMMA2_ON="false"
TINY_ON=$(getoptj '.llm_tinyllama_enabled'); [ "$TINY_ON" = "true" ] || TINY_ON="false"
QWEN_ON=$(getoptj '.llm_qwen05_enabled');    [ "$QWEN_ON" = "true" ] || QWEN_ON="false"

# choose the first enabled model; else empty
ACTIVE_TAG=""
ACTIVE_NAME="—"
if [ "$PHI3_ON" = "true" ]; then ACTIVE_TAG="phi3:mini"; ACTIVE_NAME="Phi3"; fi
if [ "$PHI2_ON" = "true" ]; then ACTIVE_TAG="phi:2.7b"; ACTIVE_NAME="Phi2"; fi
if [ "$GEMMA2_ON" = "true" ]; then ACTIVE_TAG="gemma2:2b"; ACTIVE_NAME="Gemma2"; fi
if [ "$TINY_ON" = "true" ]; then ACTIVE_TAG="tinyllama:latest"; ACTIVE_NAME="TinyLlama"; fi
if [ "$QWEN_ON" = "true" ]; then ACTIVE_TAG="qwen2:0.5b"; ACTIVE_NAME="Qwen"; fi

export OLLAMA_MODELS="$MODELS_DIR"
export LLM_OLLAMA_BASE_URL="${LLM_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export OLLAMA_BASE_URL="$LLM_OLLAMA_BASE_URL"
export LLM_ACTIVE_TAG="$ACTIVE_TAG"
export LLM_ACTIVE_NAME="$ACTIVE_NAME"

mkdir -p "$MODELS_DIR"

# --- Start/ensure Ollama (install if missing for this boot)
if ! command -v ollama >/dev/null 2>&1; then
  log "Installing Ollama (one-time per boot)…"
  curl -fsSL https://ollama.com/install.sh | OLLAMA_SKIP_START=1 sh
fi

# run server if not healthy
if ! curl -fsS "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1; then
  log "Starting internal Ollama (models at $MODELS_DIR)…"
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  # wait for server
  for i in {1..30}; do
    sleep 1
    curl -fsS "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1 && break
  done
fi

# --- Manage model pulls (idempotent)
pull_if_needed () {
  tag="$1"
  if [ -z "$tag" ]; then return; fi
  if ! curl -fsS "$OLLAMA_BASE_URL/api/tags" | grep -q ""name":"$tag""; then
    log "Pulling model: $tag"
    ollama pull "$tag" || true
  fi
}

# delete a tag if present
delete_if_present () {
  tag="$1"
  if [ -z "$tag" ]; then return; fi
  if curl -fsS "$OLLAMA_BASE_URL/api/tags" | grep -q ""name":"$tag""; then
    log "Deleting model: $tag"
    ollama rm "$tag" || true
  fi
}

# apply toggles
if [ "$PHI3_ON" = "true" ]; then pull_if_needed "phi3:mini"; else delete_if_present "phi3:mini"; fi
if [ "$PHI2_ON" = "true" ]; then pull_if_needed "phi:2.7b"; else delete_if_present "phi:2.7b"; fi
if [ "$GEMMA2_ON" = "true" ]; then pull_if_needed "gemma2:2b"; else delete_if_present "gemma2:2b"; fi
if [ "$TINY_ON" = "true" ]; then pull_if_needed "tinyllama:latest"; else delete_if_present "tinyllama:latest"; fi
if [ "$QWEN_ON" = "true" ]; then pull_if_needed "qwen2:0.5b"; else delete_if_present "qwen2:0.5b"; fi

# export hint for Python
echo "[Jarvis Prime] 🧲 Ollama store: $MODELS_DIR"
echo "[Jarvis Prime] 🧠 Active model: ${ACTIVE_TAG:-OFF} (name: ${ACTIVE_NAME}) via $OLLAMA_BASE_URL"
