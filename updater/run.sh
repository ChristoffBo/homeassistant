#!/bin/bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"

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
declare -a SKIP_LIST=()
PULL_STATUS=""
PUSH_STATUS=""

safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]][[:alnum:].:_-]*$' || echo "unknown"
}

read_config() {
  TZ=$(jq -er '.timezone // "UTC"' "$CONFIG_PATH" 2>/dev/null || echo "UTC")
  export TZ

  DRY_RUN=$(jq -er '.dry_run // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  DEBUG=$(jq -er '.debug // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  SKIP_PUSH=$(jq -er '.skip_push // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  
  # Fix: Properly handle array reading with mapfile
  mapfile -t SKIP_LIST < <(jq -er '.skip_addons[]?' "$CONFIG_PATH" 2>/dev/null || true)

  NOTIFY_ENABLED=$(jq -er '.enable_notifications // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  NOTIFY_SERVICE=$(jq -er '.notification_service // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_URL=$(jq -er '.notification_url // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TOKEN=$(jq -er '.notification_token // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TO=$(jq -er '.notification_to // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SUCCESS=$(jq -er '.notify_on_success // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  NOTIFY_ERROR=$(jq -er '.notify_on_error // true' "$CONFIG_PATH" 2>/dev/null || echo "true")
  NOTIFY_UPDATES=$(jq -er '.notify_on_updates // true' "$CONFIG_PATH" 2>/dev/null || echo "true")

  GIT_PROVIDER=$(jq -er '.git_provider // "github"' "$CONFIG_PATH" 2>/dev/null || echo "github")

  if [ "$GIT_PROVIDER" = "gitea" ]; then
    GIT_REPO=$(jq -er '.gitea_repository' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_USER=$(jq -er '.gitea_username' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_TOKEN=$(jq -er '.gitea_token' "$CONFIG_PATH" 2>/dev/null || echo "")
  else
    GIT_REPO=$(jq -er '.github_repository' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_USER=$(jq -er '.github_username' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_TOKEN=$(jq -er '.github_token' "$CONFIG_PATH" 2>/dev/null || echo "")
  fi

  GIT_AUTH_REPO="$GIT_REPO"
  if [ -n "$GIT_USER" ] && [ -n "$GIT_TOKEN" ]; then
    GIT_AUTH_REPO="${GIT_REPO/https:\/\//https://$GIT_USER:$GIT_TOKEN@}"
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

  local arch
  arch=$(uname -m)
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
  local ns_repo="${image_name/library\//}"

  # Docker Hub
  local page=1
  while :; do
    local result
    result=$(curl -sf "https://hub.docker.com/v2/repositories/$ns_repo/tags?page=$page&page_size=100") || break
    local page_tags
    page_tags=$(echo "$result" | jq -r '.results[].name')
    [ -z "$page_tags" ] && break
    tags="$tags
$page_tags"
    [ "$(echo "$result" | jq -r '.next')" = "null" ] && break
    page=$((page + 1))
  done

  # lscr.io
  if [ -z "$tags" ]; then
    tags=$(curl -sf "https://fleet.linuxserver.io/image?name=${image_name##*/}" |
      jq -r '.platforms."linux/amd64".lastUpdated.tag' 2>/dev/null || true)
  fi

  # ghcr.io
  if [ -z "$tags" ] && echo "$image_name" | grep -q "^ghcr.io/"; then
    local path="${image_name#ghcr.io/}"
    local org_repo="${path%%/*}"
    local package="${path#*/}"
    local token
    token=$(curl -sf "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token')
    if [ -n "$token" ] && [ "$token" != "null" ]; then
      tags=$(curl -sf -H "Authorization: Bearer $token" "https://ghcr.io/v2/$org_repo/$package/tags/list" | jq -r '.tags[]?')
    fi
  fi

  echo "$tags" | grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}(-[a-z0-9]+)?$' | grep -viE 'latest|dev|rc|beta' | sort -Vr | head -n1 | tee "$cache_file"
}

update_addon() {
  local addon_path="$1"
  local name
  name=$(basename "$addon_path")

  for skip in "${SKIP_LIST[@]}"; do
    [ "$name" = "$skip" ] && log "$COLOR_YELLOW" "⏭️ Skipping $name (listed)" && return
  done

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

    # Fix: Atomic file operations with better error handling
    if ! jq --arg v "$latest" '.version = $v' "$config" > "$config.tmp"; then
      log "$COLOR_RED" "❌ Failed to update $config"
      rm -f "$config.tmp"
      return
    fi
    mv "$config.tmp" "$config"
    
    if [ -f "$build" ]; then
      if ! jq --arg v "$latest" '.version = $v' "$build" > "$build.tmp"; then
        log "$COLOR_RED" "❌ Failed to update $build"
        rm -f "$build.tmp"
        return
      fi
      mv "$build.tmp" "$build"
    fi

    local changelog="$addon_path/CHANGELOG.md"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local docker_img="${image%%:*}:$latest"
    local image_url

    if [[ "$image" == ghcr.io/* ]]; then
      image_url="https://github.com/orgs/${image#ghcr.io/}/packages"
    elif [[ "$image" == *"lscr.io"* || "$image" == *"linuxserver"* ]]; then
      local image_name_clean="${image_name##*/}"
      image_url="https://fleet.linuxserver.io/image?name=${image_name_clean}"
    else
      image_url="https://hub.docker.com/r/${image%%:*}/tags"
    fi

    # Fix: Safer changelog update with error handling
    if [ -f "$changelog" ]; then
      {
        echo "## $latest ($timestamp)"
        echo "- Update from $version to $latest"
        echo "- Docker Image: [$docker_img]($image_url)"
        echo
        cat "$changelog"
      } > "$changelog.tmp"
      
      if [ -s "$changelog.tmp" ]; then
        mv "$changelog.tmp" "$changelog"
      else
        log "$COLOR_RED" "❌ Failed to update changelog for $name"
        rm -f "$changelog.tmp"
      fi
    else
      # Create changelog if it doesn't exist
      {
        echo "# Changelog"
        echo
        echo "## $latest ($timestamp)"
        echo "- Update from $version to $latest"
        echo "- Docker Image: [$docker_img]($image_url)"
        echo
      } > "$changelog"
    fi
  else
    log "$COLOR_CYAN" "✅ $name is up to date ($version)"
    UNCHANGED_ADDONS["$name"]="Up to date ($version)"
  fi
}

commit_and_push() {
  cd "$REPO_DIR" || {
    log "$COLOR_RED" "❌ Failed to change to repo directory"
    return 1
  }
  
  git config user.email "updater@local"
  git config user.name "Add-on Updater"

  if git pull --rebase; then
    PULL_STATUS="✅ Git pull (rebase) succeeded"
    log "$COLOR_GREEN" "$PULL_STATUS"
  else
    PULL_STATUS="❌ Git pull (rebase) failed"
    log "$COLOR_RED" "$PULL_STATUS"
  fi

  if [ -n "$(git status --porcelain)" ]; then
    if git add . && git commit -m "🔄 Updated add-on versions"; then
      log "$COLOR_GREEN" "✅ Changes committed successfully"
    else
      log "$COLOR_RED" "❌ Failed to commit changes"
      return 1
    fi
    
    if [ "$SKIP_PUSH" = "true" ]; then
      PUSH_STATUS="⏭️ Git push skipped (skip_push enabled)"
      log "$COLOR_YELLOW" "$PUSH_STATUS"
    elif git push "$GIT_AUTH_REPO" main; then
      PUSH_STATUS="✅ Git push succeeded"
      log "$COLOR_GREEN" "$PUSH_STATUS"
    else
      log "$COLOR_RED" "❌ Git push failed"
      PUSH_STATUS="❌ Git push failed"
      return 1
    fi
  else
    PUSH_STATUS="ℹ️ No changes to commit or push"
    log "$COLOR_CYAN" "$PUSH_STATUS"
  fi
}

main() {
  echo "" > "$LOG_FILE"
  read_config
  log "$COLOR_BLUE" "ℹ️ Starting Home Assistant Add-on Updater"

  # Fix: Better directory handling
  local temp_dir
  temp_dir=$(mktemp -d) || temp_dir="/tmp/updater_$$"
  cd "$temp_dir" || {
    log "$COLOR_RED" "❌ Failed to change to temporary directory"
    exit 1
  }
  
  [ -d "$REPO_DIR" ] && rm -rf "$REPO_DIR"

  if ! git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR"; then
    log "$COLOR_RED" "❌ Git clone failed"
    notify "Updater Error" "Git clone failed" 5
    exit 1
  fi

  # Fix: Better error handling in the loop
  for path in "$REPO_DIR"/*; do
    if [ -d "$path" ]; then
      update_addon "$path" || {
        local name
        name=$(basename "$path")
        log "$COLOR_RED" "❌ Failed to update addon $name"
        UNCHANGED_ADDONS["$name"]="Update failed"
      }
    fi
  done

  commit_and_push || {
    log "$COLOR_RED" "❌ Git operations failed"
    notify "Updater Error" "Git commit/push failed" 5
  }

  local summary="📦 Add-on Update Summary
🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')

"

  for path in "$REPO_DIR"/*; do
    [ ! -d "$path" ] && continue
    local name
    name=$(basename "$path")
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

  [ -n "$PULL_STATUS" ] && summary+="
$PULL_STATUS"
  [ -n "$PUSH_STATUS" ] && summary+="
$PUSH_STATUS"
  [ "$DRY_RUN" = "true" ] && summary+="
🔁 DRY RUN MODE ENABLED"

  notify "Add-on Updater" "$summary" 3
  log "$COLOR_BLUE" "ℹ️ Update process complete."
  
  # Clean up temporary directory
  cd / && rm -rf "$temp_dir" 2>/dev/null || true
}

main "$@"