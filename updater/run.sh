#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LAST_RUN_FILE="/data/last_run_date.txt"
LOG_FILE="/data/updater.log"

# Colors
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

# Sanity check for config vars
if [ -z "$GITHUB_REPO" ] || [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_TOKEN" ]; then
  log "$COLOR_RED" "GitHub credentials or repo URL missing in $CONFIG_PATH"
  exit 1
fi

# Git remote URL with embedded credentials for push/pull
AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")

clone_or_update_repo() {
  log "$COLOR_BLUE" "Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_BLUE" "Repository not found locally. Cloning..."
    git clone "$AUTH_REPO" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"
    log "$COLOR_GREEN" "Repository cloned successfully."
  else
    log "$COLOR_BLUE" "Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull "$AUTH_REPO" main 2>&1 | tee -a "$LOG_FILE"
    log "$COLOR_GREEN" "Repository updated."
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=5&ordering=last_updated"
  local tag=""
  tag=$(curl -s "$url" | jq -r '.results[]?.name' 2>/dev/null | grep -v 'latest' | head -n1)
  if [ -z "$tag" ] || [ "$tag" == "null" ]; then
    tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
  fi
  echo "$tag"
}

fetch_latest_linuxserver_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=5&ordering=last_updated"
  local tag=$(curl -s "$url" | jq -r '.results[]?.name' 2>/dev/null | grep -v 'latest' | head -n1)
  if [ -z "$tag" ] || [ "$tag" == "null" ]; then
    tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
  fi
  echo "$tag"
}

fetch_latest_ghcr_tag() {
  local image="$1"
  local repo_path="${image#ghcr.io/}"
  local url="https://ghcr.io/v2/${repo_path}/tags/list"
  local tags_json
  tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null)
  local tag
  tag=$(echo "$tags_json" | jq -r '.tags[]' 2>/dev/null | grep -v 'latest' | tail -n1)
  if [ -z "$tag" ] || [ "$tag" == "null" ]; then
    tag=$(echo "$tags_json" | jq -r '.tags[-1]' 2>/dev/null)
  fi
  echo "$tag"
}

get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"

  # Fix for lscr.io/linuxserver/ images to map to linuxserver/ on Docker Hub API
  if [[ "$image_no_tag" == lscr.io/linuxserver/* ]]; then
    image_no_tag="${image_no_tag#lscr.io/}"
  fi

  if [[ "$image_no_tag" == linuxserver/* ]]; then
    fetch_latest_linuxserver_tag "$image_no_tag"
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    fetch_latest_ghcr_tag "$image_no_tag"
  else
    fetch_latest_dockerhub_tag "$image_no_tag"
  fi
}

update_changelog() {
  local slug="$1"
  local changelog_file="$2"
  local latest_version="$3"
  local image="$4"

  if [ ! -f "$changelog_file" ]; then
    touch "$changelog_file"
    log "$COLOR_YELLOW" "Created new CHANGELOG.md for $slug"
  fi

  echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))" >> "$changelog_file"
  echo "" >> "$changelog_file"
  echo "    Update to latest version from $image" >> "$changelog_file"
  echo "" >> "$changelog_file"

  log "$COLOR_GREEN" "CHANGELOG.md updated for $slug"
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "No config.json or build.json found in $addon_path, skipping."
    return
  fi

  local image=""
  local slug=""
  local current_version=""
  local latest_version=""

  if [ -f "$build_file" ]; then
    local arch
    arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file")
    slug=$(jq -r '.slug // empty' "$build_file")
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
    slug=$(jq -r '.slug // empty' "$config_file")
  fi

  if [ -z "$slug" ]; then
    slug=$(basename "$addon_path")
  fi

  if [ -f "$updater_file" ]; then
    current_version=$(jq -r '.upstream_version // empty' "$updater_file")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "Addon '$slug' has no Docker image defined, skipping."
    return
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "Addon: $slug"
  log "$COLOR_BLUE" "Current version: $current_version"
  log "$COLOR_BLUE" "Image: $image"

  latest_version=$(get_latest_docker_tag "$image")
  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    log "$COLOR_YELLOW" "WARNING: Could not fetch latest docker tag for image $image"
    log "$COLOR_BLUE" "Latest version available: WARNING: Could not fetch"
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "Latest version available: $latest_version"

  if [ "$latest_version" != "$current_version" ]; then
    log "$COLOR_GREEN" "🔄 Updating add-on '$slug' from version '$current_version' to '$latest_version'"

    # Update updater.json
    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
    mv "$updater_file.tmp" "$updater_file"

    # Update config.json version field if exists
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
      if [ -f "$config_file.tmp" ]; then
        mv "$config_file.tmp" "$config_file"
      fi
    fi

    # Create or update changelog
    update_changelog "$slug" "$changelog_file" "$latest_version" "$image"

  else
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done
}

LAST_RUN=""

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')"
> "$LOG_FILE"  # Clear log at start

while true; do
  NOW_TIME=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)

  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$NOW_TIME" = "$CHECK_TIME" ] || [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_TIME on $TODAY"
    perform_update_check
    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."

    # Commit and push changes if any
    cd "$REPO_DIR"
    git add .
    if git diff-index --quiet HEAD --; then
      log "$COLOR_BLUE" "No changes detected to commit."
    else
      git config user.email "updater@local"
      git config user.name "Addon Updater"
      git commit -m "Updater: automatic version bump $(date +'%Y-%m-%d %H:%M')"
      if git push "$AUTH_REPO" main; then
        log "$COLOR_GREEN" "✅ Git push succeeded."
      else
        log "$COLOR_RED" "❌ Git push failed."
      fi
    fi

    # Always pull latest to stay in sync
    if git pull "$AUTH_REPO" main; then
      log "$COLOR_GREEN" "✅ Git pull succeeded."
    else
      log "$COLOR_RED" "❌ Git pull failed."
    fi

    sleep 60  # Prevent multiple runs in the same minute
  else
    NEXT_CHECK_TIME="$CHECK_TIME"
    log "$COLOR_BLUE" "📅 Next check scheduled at $NEXT_CHECK_TIME"
  fi

  sleep 60
done
