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
GIT_CLEAN_STATUS=""

safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]][[:alnum:].:_\-]*$' || echo "unknown"
}

read_config() {
  TZ=$(jq -er '.timezone // "UTC"' "$CONFIG_PATH" 2>/dev/null || echo "")
  export TZ

  DRY_RUN=$(jq -er '.dry_run // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  DEBUG=$(jq -er '.debug // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  SKIP_PUSH=$(jq -er '.skip_push // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  SKIP_LIST=($(jq -er '.skip_addons[]?' "$CONFIG_PATH" 2>/dev/null || echo ""))

  NOTIFY_ENABLED=$(jq -er '.enable_notifications // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SERVICE=$(jq -er '.notification_service // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_URL=$(jq -er '.notification_url // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TOKEN=$(jq -er '.notification_token // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TO=$(jq -er '.notification_to // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SUCCESS=$(jq -er '.notify_on_success // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_ERROR=$(jq -er '.notify_on_error // true' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_UPDATES=$(jq -er '.notify_on_updates // true' "$CONFIG_PATH" 2>/dev/null || echo "")

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
  if [ -z "$image" ]; then
    log "$COLOR_YELLOW" "⚠️ No image provided to get_latest_tag"
    return
  fi

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
  local ns_repo="${image_name/library\//}"
  local page=1
  while :; do
    local result=$(curl -sf "https://hub.docker.com/v2/repositories/$ns_repo/tags?page=$page&page_size=100") || {
      log "$COLOR_YELLOW" "⚠️ Docker Hub fetch failed for $ns_repo (page $page)"
      break
    }
    local page_tags=$(echo "$result" | jq -r '.results[].name')
    [ -z "$page_tags" ] && break
    tags="$tags
$page_tags"
    [ "$(echo "$result" | jq -r '.next')" = "null" ] && break
    page=$((page + 1))
  done

  if [ -z "$tags" ] && echo "$image_name" | grep -q "^ghcr.io/"; then
    local path="${image_name#ghcr.io/}"
    local org_repo="${path%%/*}"
    local package="${path#*/}"
    local token=$(curl -sf "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token') || return
    tags=$(curl -sf -H "Authorization: Bearer $token" "https://ghcr.io/v2/$org_repo/$package/tags/list" | jq -r '.tags[]?') || return
  elif [ -z "$tags" ] && echo "$image_name" | grep -q "^lscr.io/"; then
    local name="${image_name##*/}"
    tags=$(curl -sf "https://fleet.linuxserver.io/api/v1/images/$name/tags" | jq -r '.tags[].name') || return
  fi

  local filtered=$(echo "$tags" | grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}(-[a-z0-9]+)?$' | grep -viE 'latest|dev|rc|beta' | sort -Vr | head -n1)
  [ -z "$filtered" ] && return

  echo "$filtered" | tee "$cache_file"
}

update_addon() {
  local addon="$1"
  local config="$REPO_DIR/$addon/config.json"

  if [[ " ${SKIP_LIST[*]} " == *" $addon "* ]]; then
    log "$COLOR_CYAN" "⏭️  Skipping $addon"
    return
  fi

  log "$COLOR_BLUE" "🔍 Checking $addon"

  if [ ! -f "$config" ]; then
    log "$COLOR_YELLOW" "⚠️  config.json not found for $addon"
    return
  fi

  local current_image=$(safe_jq '.image' "$config")
  local current_version=$(safe_jq '.version' "$config")
  local latest_tag=$(get_latest_tag "$current_image")

  if [ -z "$latest_tag" ] || [ "$latest_tag" == "unknown" ]; then
    log "$COLOR_YELLOW" "⚠️  Could not determine latest version for $addon"
    return
  fi

  if [[ "$current_version" == "$latest_tag" ]]; then
    UNCHANGED_ADDONS["$addon"]="$current_version"
    log "$COLOR_GREEN" "✅ $addon is up to date ($current_version)"
  else
    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_PURPLE" "🧪 $addon would be updated from $current_version to $latest_tag (dry run)"
    else
      jq --arg version "$latest_tag" '.version = $version' "$config" > "$config.tmp" && mv "$config.tmp" "$config"
      UPDATED_ADDONS["$addon"]="$current_version → $latest_tag"
      log "$COLOR_YELLOW" "⬆️  $addon updated from $current_version to $latest_tag"
    fi
  fi
}

commit_and_push() {
  cd "$REPO_DIR"

  if [ "$DRY_RUN" = "true" ]; then
    log "$COLOR_PURPLE" "🧪 Dry run enabled: skipping Git commit and push"
    PUSH_STATUS="🔁 Dry run: Git push skipped"
    return
  fi

  git add .
  if ! git diff --cached --quiet; then
    git commit -m "🔄 Updated addons on $(date '+%Y-%m-%d %H:%M:%S')" || {
      log "$COLOR_YELLOW" "⚠️  Nothing to commit"
    }
    if git push origin HEAD; then
      log "$COLOR_GREEN" "📤 Git push successful"
      PUSH_STATUS="✅ Git push successful"
    else
      log "$COLOR_RED" "❌ Git push failed"
      PUSH_STATUS="❌ Git push failed"
    fi
  else
    log "$COLOR_GREEN" "✅ No changes to commit"
    PUSH_STATUS="✅ No changes to commit"
  fi
}

main() {
  log "$COLOR_DARK_BLUE" "🚀 Starting Home Assistant Add-on Updater"

  read_config

  rm -rf "$REPO_DIR"
  if git clone "$GIT_AUTH_REPO" "$REPO_DIR"; then
    cd "$REPO_DIR"
    git reset --hard HEAD && git clean -fd
    GIT_CLEAN_STATUS="🔧 Git workspace was reset before pull"
    git pull || log "$COLOR_YELLOW" "⚠️  Git pull failed"
    cd /
  else
    log "$COLOR_RED" "❌ Failed to clone repository"
    notify "Addon Updater" "❌ Failed to clone $GIT_REPO" 5
    exit 1
  fi

  for addon_path in "$REPO_DIR"/*/; do
    addon=$(basename "$addon_path")
    update_addon "$addon" || true
  done

  commit_and_push

  summary=""

  if [ "${#UPDATED_ADDONS[@]}" -gt 0 ]; then
    summary+="🆕 Updated:\n"
    for addon in "${!UPDATED_ADDONS[@]}"; do
      summary+="$addon: ${UPDATED_ADDONS[$addon]}\n"
    done
  fi

  if [ "${#UNCHANGED_ADDONS[@]}" -gt 0 ]; then
    summary+="\n✅ Unchanged:\n"
    for addon in "${!UNCHANGED_ADDONS[@]}"; do
      summary+="$addon: ${UNCHANGED_ADDONS[$addon]}\n"
    done
  fi

  summary+="\n$PUSH_STATUS"
  summary+="\n$GIT_CLEAN_STATUS"

  notify "Addon Updater Summary" "$summary" 3
}

main