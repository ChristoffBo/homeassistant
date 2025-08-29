\
    #!/usr/bin/env bash
    # shellcheck shell=bash
    set -euo pipefail

    CONFIG_PATH=/data/options.json

    jqget()   { jq -r "$1 // empty" "$CONFIG_PATH"; }
    jgbool()  { v=$(jq -r "$1 // false" "$CONFIG_PATH"); [[ "${v,,}" == "true" || "$v" == "1" ]]; }

    log(){ echo "[$(date -Iseconds)] $*"; }

    # -------- Core options (preserve existing env for other modules) --------
    export BOT_NAME="$(jqget '.bot_name'       )"
    export BOT_ICON="$(jqget '.bot_icon'       )"
    export GOTIFY_URL="$(jqget '.gotify_url'   )"
    export GOTIFY_CLIENT_TOKEN="$(jqget '.gotify_client_token')"
    export GOTIFY_APP_TOKEN="$(jqget '.gotify_app_token')"
    export JARVIS_APP_NAME="$(jqget '.jarvis_app_name')"

    export RETENTION_HOURS="$(jqget '.retention_hours')"
    export BEAUTIFY_ENABLED="$(jqget '.beautify_enabled')"
    export SILENT_REPOST="$(jqget '.silent_repost // "true"')"
    export CHAT_MOOD="$(jqget '.personality_mood // "serious"')"

    # Module toggles (unchanged behavior)
    export weather_enabled="$(jqget '.weather_enabled // false')"
    export digest_enabled="$(jqget '.digest_enabled // false')"
    export radarr_enabled="$(jqget '.radarr_enabled // false')"
    export sonarr_enabled="$(jqget '.sonarr_enabled // false')"
    export technitium_enabled="$(jqget '.technitium_enabled // false')"
    export uptimekuma_enabled="$(jqget '.uptimekuma_enabled // false')"
    export smtp_enabled="$(jqget '.smtp_enabled // false')"
    export proxy_enabled="$(jqget '.proxy_enabled // false')"
    export proxy_bind="$(jqget '.proxy_bind // "0.0.0.0"')"
    export proxy_port="$(jqget '.proxy_port // 2580')"

    # -------- Ollama settings --------
    LLM_ENABLED="$(jqget '.llm_enabled // false')"
    OLLAMA_BASE_URL="$(jqget '.ollama_base_url // "http://127.0.0.1:11434"')"
    MODELS_DIR="$(jqget '.ollama_models_dir // "/share/jarvis_prime/models"')"
    CLEANUP_ON_DISABLE="$(jqget '.llm_cleanup_on_disable // true')"
    export OLLAMA_MODELS="$MODELS_DIR"

    mkdir -p "$MODELS_DIR"

    # Preferred tiny tags for each toggle
    phi3_tag="phi3:mini"
    tiny_tag="tinyllama:latest"
    qwen_tag="qwen2.5:0.5b-instruct"
    phi2_tag="phi:2"
    gemm_tag="gemma2:2b-instruct"

    # Which toggle is on?
    phi_on=$(jq -r '.llm_phi3_enabled // false' "$CONFIG_PATH")
    tiny_on=$(jq -r '.llm_tinyllama_enabled // false' "$CONFIG_PATH")
    qwen_on=$(jq -r '.llm_qwen05_enabled // false' "$CONFIG_PATH")
    phi2_on=$(jq -r '.llm_phi2_enabled // false' "$CONFIG_PATH")
    gemm_on=$(jq -r '.llm_gemma2_enabled // false' "$CONFIG_PATH")

    # resolve active in priority order (phi3, tiny, qwen, phi2, gemma2)
    ACTIVE_TAG=""
    if [[ "${phi_on,,}"  == "true" ]]; then ACTIVE_TAG="$phi3_tag"; fi
    if [[ "${tiny_on,,}" == "true" && -z "$ACTIVE_TAG" ]]; then ACTIVE_TAG="$tiny_tag"; fi
    if [[ "${qwen_on,,}" == "true" && -z "$ACTIVE_TAG" ]]; then ACTIVE_TAG="$qwen_tag"; fi
    if [[ "${phi2_on,,}" == "true" && -z "$ACTIVE_TAG" ]]; then ACTIVE_TAG="$phi2_tag"; fi
    if [[ "${gemm_on,,}" == "true" && -z "$ACTIVE_TAG" ]]; then ACTIVE_TAG="$gemm_tag"; fi

    export OLLAMA_BASE_URL
    export LLM_ENABLED
    export LLM_CTX_TOKENS="$(jqget '.llm_ctx_tokens // 1024')"
    export LLM_ACTIVE_TAG="$ACTIVE_TAG"
    export LLM_ACTIVE_NAME="Ollama"

    # -------- Helpers --------
    have_model() {
      local tag="$1"
      local json; json="$(curl -fsS "$OLLAMA_BASE_URL/api/tags" || echo '{}')"
      if command -v jq >/dev/null 2>&1; then
        echo "$json" | jq -e '.models[] | select(.name=="'"$tag"'")' >/dev/null && return 0 || return 1
      else
        echo "$json" | grep -q '"name":"'"$tag"'"' && return 0 || return 1
      fi
    }

    pull_model() {
      local tag="$1"
      log "Pulling $tag (persisting under $OLLAMA_MODELS)…"
      curl -fsS -X POST -H 'Content-Type: application/json' \
        -d "{\"name\":\"$tag\"}" "$OLLAMA_BASE_URL/api/pull"
    }

    delete_model() {
      local tag="$1"
      log "Deleting $tag (exclusive mode)…"
      curl -fsS -X DELETE -H 'Content-Type: application/json' \
        -d "{\"name\":\"$tag\"}" "$OLLAMA_BASE_URL/api/delete" || true
    }

    ensure_serve() {
      if pgrep -f "ollama serve" >/dev/null 2>&1; then
        return 0
      fi
      log "Starting ollama serve (OLLAMA_MODELS=$OLLAMA_MODELS)…"
      nohup ollama serve >/tmp/ollama.log 2>&1 &
      for i in {1..40}; do
        sleep 0.5
        curl -fsS "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1 && return 0
      done
      log "⚠️ ollama serve not responding at $OLLAMA_BASE_URL"; return 1
    }

    # -------- Boot sequence --------
    if [[ "${LLM_ENABLED,,}" == "true" && -n "$ACTIVE_TAG" ]]; then
      ensure_serve
      # Pull once (skip if already present)
      if have_model "$ACTIVE_TAG"; then
        log "Model present: $ACTIVE_TAG"
      else
        pull_model "$ACTIVE_TAG"
      fi

      # Enforce exclusivity: remove the other candidate tags
      for tag in "$phi3_tag" "$tiny_tag" "$qwen_tag" "$phi2_tag" "$gemm_tag"; do
        if [[ "$tag" != "$ACTIVE_TAG" ]] && have_model "$tag"; then
          delete_model "$tag"
        fi
      done
    else
      if [[ "${CLEANUP_ON_DISABLE,,}" == "true" ]]; then
        ensure_serve || true
        # delete all candidate models
        for tag in "$phi3_tag" "$tiny_tag" "$qwen_tag" "$phi2_tag" "$gemm_tag"; do
          have_model "$tag" && delete_model "$tag" || true
        done
      fi
    fi

    # -------- Banner --------
    model_line="${ACTIVE_TAG:-disabled}"
    echo "──────────────────────────────────────────────"
    echo "🧠 $BOT_NAME $BOT_ICON"
    echo "⚡ Engine: ${model_line}"
    echo "💾 Store:  $OLLAMA_MODELS"
    echo "API: $OLLAMA_BASE_URL"
    echo "──────────────────────────────────────────────"

    # -------- Run bot --------
    exec python3 -u /app/bot.py
