#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

# Colors
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_DARK_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}" | tee -a /data/updater.log
}

# Clear previous log on startup
: > /data/updater.log

# Load config
TARGET_HOUR=$(jq -r '.hour' "$CONFIG_PATH")
TARGET_MINUTE=$(jq -r '.minute' "$CONFIG_PATH")
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")

# Clone or pull repo
if [ ! -d "$REPO_DIR/.git" ]; then
  log "$COLOR_BLUE" "📥 Cloning repository: $GITHUB_REPO"
  git clone "$GITHUB_REPO" "$REPO_DIR"
else
  log "$COLOR_BLUE" "🔄 Pulling latest from $GITHUB_REPO"
  cd "$REPO_DIR"
  git reset --hard HEAD
  git pull || log "$COLOR_DARK_RED" "❌ Git pull failed"
fi

# Get latest Docker tag
get_latest_docker_tag() {
  local image=$1
  local repo_name=${image#*/}
  curl -s "https://hub.docker.com/v2/repositories/${image}/tags?page_size=1" |
    jq -r '.results[0].name'
}

# Update a single addon
update_addon_if_needed() {
  local addon_path=$1
  local config_json="${addon_path}/config.json"
  local changelog="${addon_path}/CHANGELOG.md"
  local updater_file="${addon_path}/updater.json"

  if [ ! -f "$config_json" ]; then
    log "$COLOR_YELLOW" "⚠️ Skipping: No config.json in $addon_path"
    return
  fi

  local image=$(jq -r '.image' "$config_json")
  local current_version=$(jq -r '.version' "$config_json")
  local latest_tag=$(get_latest_docker_tag "$image")

  if [ -z "$latest_tag" ] || [ "$latest_tag" == "null" ]; then
    log "$COLOR_DARK_RED" "❌ Failed to get latest tag for $image"
    return
  fi

  if [ "$current_version" != "$latest_tag" ]; then
    log "$COLOR_GREEN" "🔁 Updating $(basename "$addon_path"): $current_version → $latest_tag"

    # Update config.json
    tmp_config=$(mktemp)
    jq --arg new_version "$latest_tag" '.version = $new_version' "$config_json" > "$tmp_config" && mv "$tmp_config" "$config_json"

    # Update changelog
    {
      echo ""
      echo "## ${latest_tag} ($(date '+%d-%m-%Y'))"
      echo ""
      echo "  - Updated to latest docker image tag \`$latest_tag\`"
    } >> "$changelog"

    log "$COLOR_GREEN" "📄 Updated CHANGELOG.md"

    # Update updater.json
    echo "{\"last_update\": \"$(date '+%d-%m-%Y')\"}" > "$updater_file"
    log "$COLOR_GREEN" "🗂️ Updated updater.json"

  else
    log "$COLOR_BLUE" "✅ $(basename "$addon_path") already on latest version ($current_version)"
  fi
}

# Main loop
log "$COLOR_BLUE" "⏰ Waiting to check updates daily at $TARGET_HOUR:$TARGET_MINUTE"
LAST_RUN_MINUTE=""

while true; do
  CURRENT_HOUR=$(date +%H)
  CURRENT_MINUTE=$(date +%M)
  TODAY=$(date '+%Y-%m-%d')

  if [[ "$CURRENT_HOUR" == "$TARGET_HOUR" && "$CURRENT_MINUTE" != "$LAST_RUN_MINUTE" ]]; then
    log "$COLOR_GREEN" "🚀 Starting update check at ${CURRENT_HOUR}:${CURRENT_MINUTE}"

    for dir in "$REPO_DIR"/*/; do
      if [ -d "$dir" ]; then
        update_addon_if_needed "$dir"
      fi
    done

    LAST_RUN_MINUTE="$CURRENT_MINUTE"
    log "$COLOR_GREEN" "✅ Update cycle complete at $TODAY $CURRENT_HOUR:$CURRENT_MINUTE"
  fi

  sleep 60
done
