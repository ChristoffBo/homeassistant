#!/usr/bin/env bash
set -eo pipefail

# ================
# CONFIGURATION
# ================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

# ================
# COLOR DEFINITIONS
# ================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_DARK_BLUE="\033[0;94m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# ================
# GLOBAL VARIABLES
# ================
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS

# ================
# HELPERS
# ================
safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]\.\-_]+$' || echo "unknown"
}

read_config() {
  DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
  DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
  TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
  export TZ

  GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
  GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
  GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")

  NOTIFY_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
  NOTIFY_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
  NOTIFY_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
  NOTIFY_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
  NOTIFY_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
  NOTIFY_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
  NOTIFY_ERROR=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
  NOTIFY_UPDATES=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")
  SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")

  GIT_AUTH_REPO="$GITHUB_REPO"
  if [[ -n "$GITHUB_USERNAME" && -n "$GITHUB_TOKEN" ]]; then
    GIT_AUTH_REPO="${GITHUB_REPO/https:\/\//https:\/\/$GITHUB_USERNAME:$GITHUB_TOKEN@}"
  fi
}

log() {
  local color="$1"; shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

notify() {
  local title="$1"
  local message="$2"
  local priority="${3:-0}"

  [[ "$NOTIFY_ENABLED" != "true" ]] && return
  case "$priority" in
    0) [[ "$NOTIFY_SUCCESS" != "true" ]] && return ;;
    3) [[ "$NOTIFY_UPDATES" != "true" ]] && return ;;
    5) [[ "$NOTIFY_ERROR" != "true" ]] && return ;;
  esac

  if [[ "$NOTIFY_SERVICE" == "gotify" ]]; then
    local payload
    payload=$(jq -n --arg t "$title" --arg m "$message" --argjson p "$priority" \
      '{title: $t, message: $m, priority: $p}')

    response=$(curl -s -w "%{http_code}" -o /tmp/gotify.out \
      -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$payload")

    if [[ "$response" != "200" ]]; then
      log "$COLOR_RED" "❌ Gotify notification failed (HTTP $response): $(cat /tmp/gotify.out)"
    fi
  fi
}

get_latest_tag() {
  local image="$1"
  [[ -z "$image" ]] && return

  local arch=$(uname -m)
  arch=${arch//x86_64/amd64}
  arch=${arch//aarch64/arm64}
  image="${image//\{arch\}/$arch}"

  local image_name="${image%%:*}"
  local cache_file="/tmp/tags_$(echo "$image_name" | tr '/' '_').txt"

  if [[ -f "$cache_file" && $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt 14400 ]]; then
    cat "$cache_file"
    return
  fi

  local tags=""
  if [[ "$image_name" =~ ^ghcr.io/ ]]; then
    local path="${image_name#ghcr.io/}"
    local org_repo="${path%%/*}"
    local package="${path#*/}"
    local token=$(curl -sf "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token' 2>/dev/null) || return
    local response=$(curl -sf -H "Authorization: Bearer $token" "https://ghcr.io/v2/$org_repo/$package/tags/list") || return
    echo "$response" | jq empty 2>/dev/null || { [[ "$DEBUG" == "true" ]] && echo "$response" >> "$LOG_FILE"; return; }
    tags=$(echo "$response" | jq -r '.tags[]?')
  elif [[ "$image_name" =~ ^(linuxserver|lscr.io)/ ]]; then
    local name="${image_name##*/}"
    local response=$(curl -sf "https://fleet.linuxserver.io/api/v1/images/$name/tags") || return
    echo "$response" | jq empty 2>/dev/null || { [[ "$DEBUG" == "true" ]] && echo "$response" >> "$LOG_FILE"; return; }
    tags=$(echo "$response" | jq -r '.tags[].name')
  else
    local ns_repo="${image_name/library\//}"
    local page=1
    while :; do
      local result=$(curl -sf "https://hub.docker.com/v2/repositories/${ns_repo}/tags?page=$page&page_size=100") || break
      echo "$result" | jq empty 2>/dev/null || { [[ "$DEBUG" == "true" ]] && echo "$result" >> "$LOG_FILE"; break; }
      local page_tags=$(echo "$result" | jq -r '.results[].name' 2>/dev/null)
      [[ -z "$page_tags" ]] && break
      tags+=$'\n'"$page_tags"
      [[ "$(echo "$result" | jq -r '.next')" == "null" ]] && break
      ((page++))
    done
  fi

  [[ "$DEBUG" == "true" ]] && echo "$tags" >> "$LOG_FILE"

  local semver_tags
  semver_tags=$(echo "$tags" | grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}(-[a-z0-9]+)?$' | grep -viE 'latest|dev|rc|beta')
  if [[ -n "$semver_tags" ]]; then
    echo "$semver_tags" | sort -Vr | head -n1 | tee "$cache_file"
  else
    echo "$tags" | grep -E '^[0-9]{4}([.-])[0-9]{2}\1[0-9]{2}$' | sort -Vr | head -n1 | tee "$cache_file"
  fi
}

# (no changes below here)
# The rest of the script remains the same...