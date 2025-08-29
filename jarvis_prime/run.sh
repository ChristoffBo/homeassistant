#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH=/data/options.json

log() { echo "[Jarvis Prime] $*"; }
jqget() { jq -r "$1" "$CONFIG_PATH"; }
bool() { [[ "$1" == "true" || "$1" == "1" || "$1" == "yes" || "$1" == "on" ]]; }

# -------------------------------
# Read options
# -------------------------------
LLM_ENABLED="$(jqget '.llm_enabled // false')"
LLM_CLEANUP_ON_DISABLE="$(jqget '.llm_cleanup_on_disable // true')"

PHI3_ON="$(jqget '.llm_phi3_enabled // false')"
PHI2_ON="$(jqget '.llm_phi2_enabled // false')"
GEMMA2_ON="$(jqget '.llm_gemma2_enabled // false')"
TINY_ON="$(jqget '.llm_tinyllama_enabled // false')"
QWEN05_ON="$(jqget '.llm_qwen05_enabled // false')"

# self-contained by default
# accept either llm_models_dir or ollama_models_dir (back-compat)
RAW_DIR_A="$(jqget '.llm_models_dir // empty')"
RAW_DIR_B="$(jqget '.ollama_models_dir // empty')"
if [[ -n "$RAW_DIR_A" ]]; then OLLAMA_MODELS_DIR="$RAW_DIR_A"; 
elif [[ -n "$RAW_DIR_B" ]]; then OLLAMA_MODELS_DIR="$RAW_DIR_B"; 
else OLLAMA_MODELS_DIR="/share/jarvis_prime/models"; fi

EXT_BASE_URL="$(jqget '.llm_ollama_base_url // ""')"

# Ensure persistent store exists (Ollama expects blobs/ and manifests/ inside this dir)
mkdir -p "$OLLAMA_MODELS_DIR"/{blobs,manifests} || true
chmod 755 "$OLLAMA_MODELS_DIR" || true

# -------------------------------
# If LLM disabled, optional clean and run app
# -------------------------------
if ! bool "$LLM_ENABLED"; then
  log "LLM disabled in options."
  export LLM_ACTIVE_TAG=""
  exec python3 /app/bot.py
fi

# -------------------------------
# Start or attach to Ollama
# -------------------------------
USE_EXTERNAL=0
if [[ -n "$EXT_BASE_URL" && "$EXT_BASE_URL" != "null" ]]; then
  USE_EXTERNAL=1
fi

wait_api() {
  local base="$1"
  local url="${base%/}/api/tags"
  for i in $(seq 1 120); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

if (( USE_EXTERNAL )); then
  BASE="${EXT_BASE_URL%/}"
  log "🔗 Using external Ollama at $BASE"
  if ! wait_api "$BASE"; then
    log "❌ External Ollama API not reachable at $BASE — continuing without LLM"
    export LLM_ACTIVE_TAG=""
    export OLLAMA_BASE_URL="$BASE"
    exec python3 /app/bot.py
  fi
else
  if ! command -v ollama >/dev/null 2>&1; then
    log "📦 Installing Ollama (best effort)…"
    if command -v curl >/dev/null 2>&1; then
      bash -lc 'curl -fsSL https://ollama.com/install.sh | sh' || log "⚠️  Ollama install failed (continuing)"
    else
      log "⚠️ curl not found; cannot auto-install Ollama"
    fi
  fi

  export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
  export OLLAMA_NOHISTORY=1

  # Start server with explicit models dir
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    log "🚀 Starting internal Ollama (models at $OLLAMA_MODELS_DIR)…"
    nohup env OLLAMA_MODELS="$OLLAMA_MODELS_DIR" OLLAMA_NOHISTORY=1 ollama serve >/tmp/ollama.log 2>&1 &
  fi

  if ! wait_api "http://127.0.0.1:11434"; then
    log "❌ Internal Ollama API not responding — LLM disabled."
    export LLM_ACTIVE_TAG=""
    exec python3 /app/bot.py
  fi

  BASE="http://127.0.0.1:11434"
fi

log "🗄  Ollama store: ${OLLAMA_MODELS_DIR:-external server store}"

# -------------------------------
# Desired tags from toggles
# -------------------------------
declare -A WANT
bool "$PHI3_ON"   && WANT["phi3:mini"]=1
bool "$PHI2_ON"   && WANT["phi:2.7b"]=1
bool "$GEMMA2_ON" && WANT["gemma2:2b"]=1
bool "$TINY_ON"   && WANT["tinyllama:1.1b"]=1
bool "$QWEN05_ON" && WANT["qwen2.5:0.5b-instruct"]=1

pull_tag() { curl -fsS -X POST "$BASE/api/pull"    -d "{\"name\":\"$1\"}" >/dev/null || true; }
rm_tag()   { curl -fsS -X DELETE "$BASE/api/delete" -d "{\"name\":\"$1\"}" >/dev/null || true; }

# Get current tags
CURRENT="$(curl -fsS "$BASE/api/tags" | jq -r '.models[].name' || true)"

# Pull enabled
for tag in "${!WANT[@]}"; do
  if ! grep -qx "$tag" <<< "$CURRENT"; then
    log "⬇️  Pulling model: $tag"
    pull_tag "$tag"
  else
    log "✓ Model present: $tag"
  fi
done

# Refresh current list after pulls
CURRENT="$(curl -fsS "$BASE/api/tags" | jq -r '.models[].name' || true)"

# Remove disabled
while read -r tag; do
  [[ -z "$tag" ]] && continue
  if [[ -z "${WANT[$tag]+x}" ]]; then
    log "🗑  Removing disabled model: $tag"
    rm_tag "$tag"
  fi
done <<< "$CURRENT"

# Choose active tag by priority
ACTIVE_TAG=""
for cand in phi3:mini phi:2.7b gemma2:2b tinyllama:1.1b qwen2.5:0.5b-instruct; do
  if [[ -n "${WANT[$cand]+x}" ]]; then
    ACTIVE_TAG="$cand"
    break
  fi
done

export OLLAMA_BASE_URL="$BASE"
export LLM_ACTIVE_TAG="$ACTIVE_TAG"
case "$ACTIVE_TAG" in
  phi3:mini)                export LLM_ACTIVE_NAME="Phi3" ;;
  phi:2.7b)                 export LLM_ACTIVE_NAME="Phi2" ;;
  gemma2:2b)                export LLM_ACTIVE_NAME="Gemma2" ;;
  tinyllama:1.1b)           export LLM_ACTIVE_NAME="TinyLlama" ;;
  qwen2.5:0.5b-instruct)    export LLM_ACTIVE_NAME="Qwen" ;;
  *)                        export LLM_ACTIVE_NAME="—" ;;
esac

log "🔧 Active model: ${LLM_ACTIVE_TAG:-none} (name: ${LLM_ACTIVE_NAME}) via ${BASE}"
log "📂 Expect to see 'blobs' and 'manifests' inside: $OLLAMA_MODELS_DIR"

exec python3 /app/bot.py
