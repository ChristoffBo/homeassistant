#!/bin/bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

# ======================
# COLOR DEFINITIONS
# ======================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_DARK_BLUE="\033[0;94m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# ======================
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS

safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]][[:alnum:].:_-]*$' || echo "unknown"
}

read_config() {
  DRY_RUN=$(jq -er '.dry_run // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  DEBUG=$(jq -er '.debug // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  TZ=$(jq -er '.timezone // "UTC"' "$CONFIG_PATH" 2>/dev/null || echo "")
  export TZ

  GITHUB_REPO=$(jq -er '.repository // .github_repo // empty' "$CONFIG_PATH" 2>/dev/null || echo "")
  GITHUB_USERNAME=$(jq -er '.gituser // .github_username // empty' "$CONFIG_PATH" 2>/dev/null || echo "")
  GITHUB_TOKEN=$(jq -er '.gittoken // .github_token // empty' "$CONFIG_PATH" 2>/dev/null || echo "")

  NOTIFY_ENABLED=$(jq -er '.enable_notifications // .notifications_enabled // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SERVICE=$(jq -er '.notification_service // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_URL=$(jq -er '.notification_url // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TOKEN=$(jq -er '.notification_token // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TO=$(jq -er '.notification_to // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SUCCESS=$(jq -er '.notify_on_success // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_ERROR=$(jq -er '.notify_on_error // true' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_UPDATES=$(jq -er '.notify_on_updates // true' "$CONFIG_PATH" 2>/dev/null || echo "")
  SKIP_PUSH=$(jq -er '.skip_push // false' "$CONFIG_PATH" 2>/dev/null || echo "")

  GIT_AUTH_REPO="$GITHUB_REPO"
  if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
    GIT_AUTH_REPO="${GITHUB_REPO/https:\/\//https://$GITHUB_USERNAME:$GITHUB_TOKEN@}"
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

  [ "$NOTIFY_ENABLED" != "true" ] && return
  case "$priority" in
    0) [ "$NOTIFY_SUCCESS" != "true" ] && return ;;
    3) [ "$NOTIFY_UPDATES" != "true" ] && return ;;
    5) [ "$NOTIFY_ERROR" != "true" ] && return ;;
  esac

  if [ "$NOTIFY_SERVICE" = "gotify" ]; then
    local payload
    payload=$(jq -n --arg t "$title" --arg m "$message" --argjson p "$priority" '{title: $t, message: $m, priority: $p}')
    curl -s -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" -H "Content-Type: application/json" -d "$payload" > /dev/null || log "$COLOR_RED" "❌ Gotify notification failed"
  fi
}

get_latest_tag() {
  local image="$1"
  [ -z "$image" ] && return

  local arch=$(uname -m)
  arch=${arch//x86_64/amd64}
  arch=${arch//aarch64/arm64}
  image="${image//\{arch\}/$arch}"
  local image_name="${image%%:*}"
  local cache_file="/tmp/tags_$(echo "$image_name" | tr '/' '_').txt"

  if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt 14400 ]; then
    cat "$cache_file"
    return
  fi

  local tags=""
  if echo "$image_name" | grep -q "^ghcr.io/"; then
    local path="${image_name#ghcr.io/}"
    local org_repo="${path%%/*}"
    local package="${path#*/}"
    local token=$(curl -sf "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token')
    tags=$(curl -sf -H "Authorization: Bearer $token" "https://ghcr.io/v2/$org_repo/$package/tags/list" | jq -r '.tags[]?')
  elif echo "$image_name" | grep -qE "^(linuxserver|lscr.io)/"; then
    local name="${image_name##*/}"
    tags=$(curl -sf "https://fleet.linuxserver.io/api/v1/images/$name/tags" | jq -r '.tags[].name')
  else
    local ns_repo="${image_name/library\//}"
    local page=1
    while :; do
      local result=$(curl -sf "https://hub.docker.com/v2/repositories/$ns_repo/tags?page=$page&page_size=100") || break
      local page_tags=$(echo "$result" | jq -r '.results[].name')
      [ -z "$page_tags" ] && break
      tags="$tags
$page_tags"
      [ "$(echo "$result" | jq -r '.next')" = "null" ] && break
      page=$((page + 1))
    done
  fi

  echo "$tags" | grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}(-[a-z0-9]+)?$' | grep -viE 'latest|dev|rc|beta' | sort -Vr | head -n1 | tee "$cache_file"
}

update_addon() {
  local addon_path="$1"
  local name=$(basename "$addon_path")

  if [ "$name" = "updater" ] || [ "$name" = "heimdall" ]; then
    log "$COLOR_YELLOW" "⏭️ Skipping $name (excluded)"
    return
  fi

  log "$COLOR_DARK_BLUE" "🔍 Checking $name"

  local config="$addon_path/config.json"
  local build="$addon_path/build.json"
  local image version latest

  image=$(jq -r '.image // empty' "$config" 2>/dev/null || echo "")
  version=$(safe_jq '.version' "$config")

  if [ -z "$image" ] && [ -f "$build" ]; then
    image=$(jq -r '.build_from.amd64 // .build_from | strings' "$build" 2>/dev/null || echo "")
    version=$(safe_jq '.version' "$build")
  fi

  if [ -z "$image" ]; then
    log "$COLOR_YELLOW" "⚠️ No image defined for $name"
    UNCHANGED_ADDONS["$name"]="No image defined"
    return
  fi

  latest=$(get_latest_tag "$image")
  if [ -z "$latest" ]; then
    log "$COLOR_YELLOW" "⚠️ No valid version tag found for $image"
    UNCHANGED_ADDONS["$name"]="No valid tag"
    return
  fi

  if [ "$version" != "$latest" ]; then
    log "$COLOR_GREEN" "⬆️ $name updated from $version to $latest"
    UPDATED_ADDONS["$name"]="$version → $latest"

    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_PURPLE" "💡 Dry run active: skipping update of $name"
      return
    fi

    jq --arg v "$latest" '.version = $v' "$config" > "$config.tmp" && mv "$config.tmp" "$config"
    if [ -f "$build" ]; then
      jq --arg v "$latest" '.version = $v' "$build" > "$build.tmp" && mv "$build.tmp" "$build"
    fi
  else
    log "$COLOR_CYAN" "✅ $name is up to date ($version)"
    UNCHANGED_ADDONS["$name"]="Up to date ($version)"
  fi
}

commit_and_push() {
  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "Add-on Updater"

  if [ -n "$(git status --porcelain)" ]; then
    git add . && git commit -m "🔄 Updated add-on versions" || return
    [ "$SKIP_PUSH" = "true" ] && return
    git push "$GIT_AUTH_REPO" main || log "$COLOR_RED" "❌ Git push failed"
  else
    log "$COLOR_CYAN" "ℹ️ No changes to commit"
  fi
}

main() {
  echo "" > "$LOG_FILE"
  read_config
  log "$COLOR_BLUE" "ℹ️ Starting Home Assistant Add-on Updater"

  [ -d "$REPO_DIR" ] && rm -rf "$REPO_DIR"

  git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" || {
    log "$COLOR_RED" "❌ Git clone failed"
    notify "Updater Error" "Git clone failed" 5
    exit 1
  }

  for path in "$REPO_DIR"/*; do
    [ -d "$path" ] && update_addon "$path"
  done

  commit_and_push

  local summary="📦 Add-on Update Summary
"
  summary+="🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')

"

  for path in "$REPO_DIR"/*; do
    [ ! -d "$path" ] && continue
    local name=$(basename "$path")
    local status=""

    if [ -n "${UPDATED_ADDONS[$name]}" ]; then
      status="🔄 ${UPDATED_ADDONS[$name]}"
    elif [ -n "${UNCHANGED_ADDONS[$name]}" ]; then
      status="✅ ${UNCHANGED_ADDONS[$name]}"
    else
      status="⏭️ Skipped"
    fi

    summary+="$name: $status
"
  done

  [ "$DRY_RUN" = "true" ] && summary+="
🔁 DRY RUN MODE ENABLED"
  notify "Add-on Updater" "$summary" 3
  log "$COLOR_BLUE" "ℹ️ Update process complete."
}

main
