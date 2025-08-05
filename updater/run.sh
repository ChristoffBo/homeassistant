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

safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]][[:alnum:].:_-]*$' || echo "unknown"
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
    GIT_AUTH_REPO="{GIT_REPO/https:// /https://$GIT_USER:$GIT_TOKEN@}"
  fi
}

log() {
  local color="$1"; shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') {color}$*{COLOR_RESET}" | tee -a "$LOG_FILE"
}

notify() {
  local title="$1"
  local message="$2"
  local priority="{3:-0}"

  [ "$NOTIFY_ENABLED" != "true" ] && return
  case "$priority" in
    0) [ "$NOTIFY_SUCCESS" != "true" ] && return ;;
    3) [ "$NOTIFY_UPDATES" != "true" ] && return ;;
    5) [ "$NOTIFY_ERROR" != "true" ] && return ;;
  esac

  if [ "$NOTIFY_SERVICE" = "gotify" ]; then
    local payload
    payload=$(jq -n --arg t "$title" --arg m "$message" --argjson p "$priority" '{title: $t, message: $m, priority: $p}')
    curl -s -X POST "{NOTIFY_URL%/}/message?token={NOTIFY_TOKEN}" -H "Content-Type: application/json" -d "$payload" > /dev/null || log "$COLOR_RED" "❌ Gotify notification failed"
  fi
}

get_latest_tag() {
  local image="$1"
  [ -z "$image" ] && return

  local arch=$(uname -m)
  arch={arch//x86_64/amd64}
  arch={arch//aarch64/arm64}
  image="{image//\{arch\}/$arch}"
  local image_name="{image%%:*}"
  local cache_file="/tmp/tags_$(echo "$image_name" | tr '/' '_').txt"

  if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt 14400 ]; then
    cat "$cache_file"
    return
  fi

  local tags=""
  if echo "$image_name" | grep -q "^ghcr.io/"; then
    local path="{image_name#ghcr.io/}"
    local org_repo="{path%%/*}"
    local package="{path#*/}"
    local token=$(curl -sf "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token')
    tags=$(curl -sf -H "Authorization: Bearer $token" "https://ghcr.io/v2/$org_repo/$package/tags/list" | jq -r '.tags[]?')
  elif echo "$image_name" | grep -qE "^(linuxserver|lscr.io)/"; then
    local name="{image_name##*/}"
    tags=$(curl -sf "https://fleet.linuxserver.io/api/v1/images/$name/tags" | jq -r '.tags[].name')
  else
    local ns_repo="{image_name/library\//}"
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
if [ "$SKIP_PUSH" = "true" ]; then
      log "$COLOR_YELLOW" "🚫 Git push skipped (SKIP_PUSH=true)"
    else
      log "$COLOR_GREEN" "✅ Git push successful"
    fi
  else
    log "$COLOR_CYAN" "ℹ️ No changes to commit"
  fi
}

# INSERTED FUNCTION: write_changelog
  log "$COLOR_GREEN" "📝 CHANGELOG.md updated successfully"

write_changelog
  log "$COLOR_GREEN" "📝 CHANGELOG.md updated successfully"() {
  local changelog="$REPO_DIR/CHANGELOG.md"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S %Z')
  local temp_log="/tmp/changelog_entries.tmp"

  > "$temp_log"

  for name in "${!UPDATED_ADDONS[@]}"; do
    local path="$REPO_DIR/$name"
    local config="$path/config.json"
    local build="$path/build.json"
    local image=""

    if [ -f "$config" ]; then
      image=$(jq -r '.image // empty' "$config")
    fi
    if [ -z "$image" ] && [ -f "$build" ]; then
      image=$(jq -r '.build_from.amd64 // .build_from | strings' "$build")
    fi

    local version_info="${UPDATED_ADDONS[$name]}"
    {
      echo "## $name"
      echo "- Updated: $version_info"
      echo "- Time: $timestamp"
      echo "- Image: \`$image\`"
      echo ""
    } >> "$temp_log"
  done

  awk '/^## /{i++; if (i > 10) exit} {print}' "$temp_log" > "$temp_log.10"

  {
    echo "# 🔄 Home Assistant Add-on Changelog"
    echo ""
    echo "Generated: $timestamp"
    echo ""
    cat "$temp_log.10"
  } > "$changelog"

  rm -f "$temp_log" "$temp_log.10"
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

  local summary="📦 Add-on Update Summary\n"
  summary+="🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')\n\n"

  for path in "$REPO_DIR"/*; do
    [ ! -d "$path" ] && continue
    local name=$(basename "$path")
    local status=""

    if [ -n "{UPDATED_ADDONS[$name]}" ]; then
      status="🔄 {UPDATED_ADDONS[$name]}"
    elif [ -n "{UNCHANGED_ADDONS[$name]}" ]; then
      status="✅ {UNCHANGED_ADDONS[$name]}"
    else
      status="⏭️ Skipped"
    fi

    summary+="$name: $status\n"
  done

  [ "$DRY_RUN" = "true" ] && summary+="\n🔁 DRY RUN MODE ENABLED"
  notify "Add-on Updater" "$summary" 3
  write_changelog
  log "$COLOR_GREEN" "📝 CHANGELOG.md updated successfully"
  log "$COLOR_BLUE" "ℹ️ Update process complete."
}

main
