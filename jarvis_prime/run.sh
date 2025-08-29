#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json

log() { echo "[Jarvis Prime] $*"; }

jqget() { jq -r "$1" "$CONFIG_PATH"; }

bool() { # convert jq 'true/false' or strings to 0/1
  local v="$1"
  if [[ "$v" == "true" || "$v" == "1" || "$v" == "yes" ]]; then
    echo 1
  else
    echo 0
  fi
}

# -------------------------------
# Read options (with sane defaults)
# -------------------------------
LLM_ENABLED="$(jqget '.llm_enabled // false')"
LLM_CLEANUP_ON_DISABLE="$(jqget '.llm_cleanup_on_disable // true')"

# Optional model toggles (default false if missing)
PHI3_ON="$(jqget '.llm_phi3_enabled // false')"
PHI2_ON="$(jqget '.llm_phi2_enabled // false')"
GEMMA2_ON="$(jqget '.llm_gemma2_enabled // false')"
TINY_ON="$(jqget '.llm_tinyllama_enabled // false')"
QWEN05_ON="$(jqget '.llm_qwen05_enabled // false')"

# User may point to an existing Ollama server (e.g., HA add-on) with custom port
EXT_BASE_URL="$(jqget '.llm_ollama_base_url // ""')"

# Local models dir only used when we run our own server
OLLAMA_MODELS_DIR="$(jqget '.ollama_models_dir // "/share/jarvis_prime/ollama_models"')"
mkdir -p "$OLLAMA_MODELS_DIR" || true

# -------------------------------
# Decide backend: external vs internal server
# -------------------------------
USE_EXTERNAL=0
if [[ -n "$EXT_BASE_URL" && "$EXT_BASE_URL" != "null" ]]; then
  USE_EXTERNAL=1
fi

# Helper: wait for API readiness
wait_api() {
  local base="$1"
  local url="${base%/}/api/tags"
  for i in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

# -------------------------------
# If LLM globally disabled, optionally clean up and exit
# -------------------------------
if [[ "$LLM_ENABLED" != "true" ]]; then
  log "LLM is disabled in options."
  if (( $(bool "$LLM_CLEANUP_ON_DISABLE") )); then
    if (( USE_EXTERNAL )); then
      BASE="${EXT_BASE_URL%/}"
      if wait_api "$BASE"; then
        log "🧹 Cleaning up remote Ollama models (disabled state)…"
        curl -fsS "$BASE/api/tags" | jq -r '.models[].name' | xargs -r -I{} curl -fsS -X DELETE "$BASE/api/delete" -d "{\"name\":\"{}\"}" >/dev/null || true
      fi
    else
      if command -v ollama >/dev/null 2>&1; then
        log "🧹 Cleaning up local Ollama models (disabled state)…"
        ollama list | awk 'NR>1 {print $1}' | xargs -r -n1 ollama rm || true
      fi
    fi
  fi
  export LLM_ACTIVE_TAG=""
  exec python3 /app/bot.py
fi

# -------------------------------
# Start or attach to Ollama
# -------------------------------
BASE_URL=""
if (( USE_EXTERNAL )); then
  BASE_URL="${EXT_BASE_URL%/}"
  log "🔗 Using external Ollama at $BASE_URL"
  if ! wait_api "$BASE_URL"; then
    log "❌ External Ollama API not reachable at $BASE_URL — continuing without LLM"
    export LLM_ACTIVE_TAG=""
    export OLLAMA_BASE_URL="$BASE_URL"
    exec python3 /app/bot.py
  fi
else
  # Internal server path
  if ! command -v ollama >/dev/null 2>&1; then
    log "📦 Installing Ollama (best effort)…"
    if command -v curl >/dev/null 2>&1; then
      bash -lc 'curl -fsSL https://ollama.com/install.sh | sh' || log "⚠️  Ollama install script failed (continuing)"
    else
      log "⚠️ curl not found; cannot auto-install Ollama"
    fi
  fi

  if ! command -v ollama >/dev/null 2>&1; then
    log "❌ Ollama binary not available. LLM disabled."
    export LLM_ACTIVE_TAG=""
    exec python3 /app/bot.py
  fi

  export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
  export OLLAMA_NOHISTORY=1

  # Start server if not up
  CHECK_URL="http://127.0.0.1:11434/api/tags"
  if ! curl -fsS "$CHECK_URL" >/dev/null 2>&1; then
    log "🚀 Starting Ollama server…"
    nohup ollama serve >/tmp/ollama.log 2>&1 &
  fi

  if ! wait_api "http://127.0.0.1:11434"; then
    log "❌ Internal Ollama API not responding — LLM disabled."
    export LLM_ACTIVE_TAG=""
    exec python3 /app/bot.py
  fi
  BASE_URL="http://127.0.0.1:11434"
fi

# -------------------------------
# Determine which tags are enabled by toggles
# -------------------------------
declare -A WANT
(( $(bool "$PHI3_ON") ))   && WANT["phi3:mini"]=1
(( $(bool "$PHI2_ON") ))   && WANT["phi:2.7b"]=1
(( $(bool "$GEMMA2_ON") )) && WANT["gemma2:2b"]=1
(( $(bool "$TINY_ON") ))   && WANT["tinyllama:1.1b"]=1
(( $(bool "$QWEN05_ON") )) && WANT["qwen2.5:0.5b-instruct"]=1

# Pull enabled (via API if external, CLI if internal)
pull_tag() {
  local tag="$1"
  if (( USE_EXTERNAL )); then
    curl -fsS -X POST "$BASE_URL/api/pull" -d "{\"name\":\"$tag\"}" >/dev/null
  else
    ollama pull "$tag"
  fi
}

rm_tag() {
  local tag="$1"
  if (( USE_EXTERNAL )); then
    curl -fsS -X DELETE "$BASE_URL/api/delete" -d "{\"name\":\"$tag\"}" >/dev/null
  else
    ollama rm "$tag" || true
  fi
}

# Current models
CURRENT=$(curl -fsS "$BASE_URL/api/tags" | jq -r '.models[].name' || true)

# Pull enabled
for tag in "${!WANT[@]}"; do
  if ! grep -qx "$tag" <<< "$CURRENT"; then
    log "⬇️  Pulling model: $tag"
    pull_tag "$tag" || log "⚠️  Pull failed for $tag"
  else
    log "✓ Model present: $tag"
  fi
done

# Remove disabled
while read -r tag; do
  [[ -z "$tag" ]] && continue
  if [[ -z "${WANT[$tag]+x}" ]]; then
    log "🗑  Removing disabled model: $tag"
    rm_tag "$tag"
  fi
done <<< "$CURRENT"

# Prioritize the active tag
ACTIVE_TAG=""
for cand in phi3:mini phi:2.7b gemma2:2b tinyllama:1.1b qwen2.5:0.5b-instruct; do
  if [[ -n "${WANT[$cand]+x}" ]]; then
    ACTIVE_TAG="$cand"
    break
  fi
done

# Export for Python app
export OLLAMA_BASE_URL="$BASE_URL"
export LLM_ACTIVE_TAG="$ACTIVE_TAG"

# Human-friendly short name
case "$ACTIVE_TAG" in
  phi3:mini)                export LLM_ACTIVE_NAME="Phi3" ;;
  phi:2.7b)                 export LLM_ACTIVE_NAME="Phi2" ;;
  gemma2:2b)                export LLM_ACTIVE_NAME="Gemma2" ;;
  tinyllama:1.1b)           export LLM_ACTIVE_NAME="TinyLlama" ;;
  qwen2.5:0.5b-instruct)    export LLM_ACTIVE_NAME="Qwen" ;;
  *)                        export LLM_ACTIVE_NAME="—" ;;
esac

log "🔧 Active model: ${LLM_ACTIVE_TAG:-none} (name: ${LLM_ACTIVE_NAME}) via ${BASE_URL}"

# Hand off to the Python app
exec python3 /app/bot.py
