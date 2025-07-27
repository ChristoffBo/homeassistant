#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LAST_RUN_FILE="/data/last_run_date.txt"

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "❌ ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# 🧱 Clone or update the repo
clone_or_update_repo() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_YELLOW" "📁 Cloning repo: $GITHUB_REPO"
    git clone "$GIT_AUTH_REPO" "$REPO_DIR"
  else
    log "$COLOR_YELLOW" "🔄 Updating repo: $GITHUB_REPO"
    cd "$REPO_DIR"
    git reset --hard
    git clean -fd
    git pull origin main
  fi
}

# 🐳 Fetch latest Docker Hub tag
get_latest_docker_tag() {
  local image="$1"
  local repo="${image#*/}"  # remove registry prefix
  local api_url="https://hub.docker.com/v2/repositories/${repo}/tags?page_size=1&page=1&ordering=last_updated"
  curl -s "$api_url" | jq -r '.results[0].name // "latest"'
}

# 🔁 Check if the add-on needs update
update_addon_if_needed() {
  local addon_dir="$1"
  local config_file="$addon_dir/config.json"

  if [ ! -f "$config_file" ]; then
    log "$COLOR_RED" "⚠️ Missing config.json in $addon_dir"
    return
  fi

  local image
  image=$(jq -r '.image // empty' "$config_file")
  if [ -z "$image" ]; then
    log "$COLOR_RED" "⚠️ No image defined for $addon_dir"
    return
  fi

  local current_tag
  current_tag=$(jq -r '.version // "unknown"' "$config_file")
  local latest_tag
  latest_tag=$(get_latest_docker_tag "$image")

  if [ "$current_tag" != "$latest_tag" ]; then
    log "$COLOR_YELLOW" "⬆️  Update available for $addon_dir"
    log "$COLOR_YELLOW" "🔁 Updating version: $current_tag → $latest_tag"
    jq --arg version "$latest_tag" '.version = $version' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    # Append changelog
    local changelog_file="$addon_dir/CHANGELOG.md"
    local today
    today=$(date '+%d-%m-%Y')
    local changelog_entry="### 🗓️ $latest_tag ($today)\n\n- 🔄 Auto-updated by add-on updater\n"
    echo -e "$changelog_entry\n$(cat "$changelog_file" 2>/dev/null)" > "$changelog_file"

    log "$COLOR_GREEN" "✅ Updated $addon_dir to version $latest_tag"
  else
    log "$COLOR_BLUE" "👌 $addon_dir is up to date ($current_tag)"
  fi
}

# 🔍 Perform full update check
perform_update_check() {
  clone_or_update_repo

  for dir in "$REPO_DIR"/*/; do
    [ -d "$dir" ] || continue
    update_addon_if_needed "$dir"
  done
}

# 🚀 Initial run
log "$COLOR_GREEN" "🚀 HomeAssistant Add-on Updater started at $(date '+%d-%m-%Y %H:%M')"

perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

log "$COLOR_BLUE" "🕒 Waiting until daily check time: $CHECK_TIME"

# ⏱️ Loop forever and check at scheduled time
while true; do
  NOW=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=$(cat "$LAST_RUN_FILE" 2>/dev/null || echo "")

  if [ "$NOW" == "$CHECK_TIME" ] && [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW"
    perform_update_check
    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."
    sleep 60  # Prevent repeat within the same minute
  fi

  sleep 30
done
