#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
log(){ echo "[Jarvis Prime] $*"; }

jget(){ jq -r "$1 // empty" "$CONFIG_PATH" 2>/dev/null || true; }

# Core passthrough env
export BOT_NAME="$(jget '.bot_name')"
export BOT_ICON="$(jget '.bot_icon')"
export GOTIFY_URL="$(jget '.gotify_url')"
export GOTIFY_CLIENT_TOKEN="$(jget '.gotify_client_token')"
export GOTIFY_APP_TOKEN="$(jget '.gotify_app_token')"
export JARVIS_APP_NAME="$(jget '.jarvis_app_name')"
export RETENTION_HOURS="$(jget '.retention_hours')"
export BEAUTIFY_ENABLED="$(jget '.beautify_enabled')"
export SILENT_REPOST="$(jget '.silent_repost // "true"')"
export CHAT_MOOD="$(jget '.personality_mood // "serious"')"

# module toggles
export weather_enabled="$(jget '.weather_enabled // false')"
export digest_enabled="$(jget '.digest_enabled // false')"
export technitium_enabled="$(jget '.technitium_enabled // false')"
export uptimekuma_enabled="$(jget '.uptimekuma_enabled // false')"
export smtp_enabled="$(jget '.smtp_enabled // false')"
export proxy_enabled="$(jget '.proxy_enabled // false')"
export proxy_bind="$(jget '.proxy_bind // "0.0.0.0"')"
export proxy_port="$(jget '.proxy_port // 2580')"

# Ollama
LLM_ENABLED="$(jget '.llm_enabled // false')"
OLLAMA_BASE_URL="$(jget '.ollama_base_url // "http://127.0.0.1:11434"')"
MODELS_DIR="$(jget '.ollama_models_dir // "/share/jarvis_prime/models"')"
export OLLAMA_MODELS="$MODELS_DIR"
mkdir -p "$MODELS_DIR"

# lightest tags (q2_K)
phi3_tag="phi3:3.8b-mini-4k-instruct-q2_K"
tiny_tag="tinyllama:1.1b-chat-v1-q2_K"
qwen_tag="qwen2.5:0.5b-instruct-q2_K"
phi2_tag="phi:2.7b-chat-v2-q2_K"
gemm_tag="gemma2:2b-instruct-q2_K"

phi3_on="$(jget '.llm_phi3_enabled // false')"
tiny_on="$(jget '.llm_tinyllama_enabled // false')"
qwen_on="$(jget '.llm_qwen05_enabled // false')"
phi2_on="$(jget '.llm_phi2_enabled // false')"
gemm_on="$(jget '.llm_gemma2_enabled // false')"

ACTIVE_TAG=""
if [[ "${phi3_on,,}" == "true" ]]; then ACTIVE_TAG="$phi3_tag"; fi
if [[ -z "$ACTIVE_TAG" && "${tiny_on,,}" == "true" ]]; then ACTIVE_TAG="$tiny_tag"; fi
if [[ -z "$ACTIVE_TAG" && "${qwen_on,,}" == "true" ]]; then ACTIVE_TAG="$qwen_tag"; fi
if [[ -z "$ACTIVE_TAG" && "${phi2_on,,}" == "true" ]]; then ACTIVE_TAG="$phi2_tag"; fi
if [[ -z "$ACTIVE_TAG" && "${gemm_on,,}" == "true" ]]; then ACTIVE_TAG="$gemm_tag"; fi

export OLLAMA_BASE_URL
export LLM_ENABLED
export LLM_ACTIVE_TAG="$ACTIVE_TAG"
export LLM_CTX_TOKENS="$(jget '.llm_ctx_tokens // 1024')"

ensure_ollama() {
  if command -v ollama >/dev/null 2>&1; then return 0; fi
  log "Installing Ollama…"
  curl -fsSL https://ollama.com/install.sh | sh
}

ensure_serve() {
  if pgrep -f "ollama serve" >/dev/null 2>&1; then return 0; fi
  log "Starting ollama serve (store=$OLLAMA_MODELS)…"
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  for i in {1..60}; do
    sleep 0.5
    curl -fsS "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1 && return 0
  done
  log "Ollama API not responding at $OLLAMA_BASE_URL"
  return 1
}

have_model() {
  local tag="$1"
  local json; json="$(curl -fsS "$OLLAMA_BASE_URL/api/tags" || echo '{}')"
  python3 - "$tag" <<'PY' 2>/dev/null
import sys, json
j=json.loads(sys.stdin.read() or "{}")
names=[m.get("name","") for m in (j.get("models") or []) if isinstance(m,dict)]
sys.exit(0 if sys.argv[1] in names else 1)
PY
}

pull_model() {
  local tag="$1"
  log "Pulling $tag (persist to $OLLAMA_MODELS)…"
  curl -fsS -X POST -H 'Content-Type: application/json' -d "{"model":"$tag"}" "$OLLAMA_BASE_URL/api/pull" >/dev/null
}

delete_model() {
  local tag="$1"
  log "Deleting $tag…"
  curl -fsS -X DELETE -H 'Content-Type: application/json' -d "{"model":"$tag"}" "$OLLAMA_BASE_URL/api/delete" >/dev/null || true
}

# Boot
ensure_ollama
if [[ "${LLM_ENABLED,,}" == "true" && -n "$ACTIVE_TAG" ]]; then
  ensure_serve
  if have_model "$ACTIVE_TAG"; then
    log "Model present: $ACTIVE_TAG"
  else
    pull_model "$ACTIVE_TAG"
  fi
  for tag in "$phi3_tag" "$tiny_tag" "$qwen_tag" "$phi2_tag" "$gemm_tag"; do
    [[ "$tag" != "$ACTIVE_TAG" ]] && have_model "$tag" && delete_model "$tag" || true
  done
fi

echo "Jarvis Prime: Engine=${ACTIVE_TAG:-disabled} Store=$OLLAMA_MODELS API=$OLLAMA_BASE_URL"

exec python3 -u /app/bot.py
