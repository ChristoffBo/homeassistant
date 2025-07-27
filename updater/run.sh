#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE=/data/update.log

# Colored output
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
  echo -e "${COLOR_RED}ERROR: Config file $CONFIG_PATH not found!${COLOR_RESET}"
  exit 1
fi

# Read config options
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

# GitHub authentication header for API calls if token provided
GITHUB_AUTH_HEADER=""
if [ -n "$GITHUB_TOKEN" ]; then
  GITHUB_AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"
fi

# Clear log at start
> "$LOG_FILE"

clone_or_update_repo() {
  log "$COLOR_BLUE" "Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "Repository not found locally. Cloning..."
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1
    else
      git clone "$GITHUB_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1
    fi
    log "$COLOR_GREEN" "Repository cloned successfully."
  else
    log "$COLOR_BLUE" "Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull >> "$LOG_FILE" 2>&1 || {
      log "$COLOR_RED" "Failed to pull latest changes."
    }
    log "$COLOR_GREEN" "Repository updated."
  fi
}

# Fetch latest real docker tag (not "latest") from DockerHub or LinuxServer.io
get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"

  # Handle lscr.io/linuxserver prefix
  if [[ "$image_no_tag" == lscr.io/linuxserver/* ]]; then
    image_no_tag="${image_no_tag#lscr.io/}"
  fi

  # Compose Docker Hub API URL for tags
  local url="https://registry.hub.docker.com/v2/repositories/$image_no_tag/tags?page_size=10&ordering=last_updated"

  # Fetch tags JSON
  local tags_json
  tags_json=$(curl -s "$url")

  # Extract first non-"latest" tag
  local tag
  tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | head -n 1)

  if [ -z "$tag" ]; then
    # fallback: if no tags found, maybe return empty string
    echo ""
  else
    echo "$tag"
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local updater_file="$addon_path/updater.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  # Check existence of config or build files
  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "Add-on '$(basename "$addon_path")' has no config.json or build.json, skipping."
    return
  fi

  # Determine image from build.json or config.json
  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi
  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
  fi

  # Get slug (fallback to folder name)
  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  # Read current version from updater.json or config.json
  local current_version=""
  if [ -f "$updater_file" ]; then
    current_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
  fi
  if [ -z "$current_version" ] && [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "Addon: $slug"
  log "$COLOR_BLUE" "Current version: $current_version"
  log "$COLOR_BLUE" "Image: $image"

  # Get latest tag (not "latest")
  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "WARNING: Could not fetch latest docker tag for image $image"
    log "$COLOR_BLUE" "Latest version available: unknown"
    log "$COLOR_BLUE" "Add-on '$slug' is assumed up-to-date ✔"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "Latest version available: $latest_version"

  # Compare versions and update only if different and latest_version not empty or "latest"
  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ] && [ -n "$latest_version" ]; then
    log "$COLOR_GREEN" "🔄 Updating add-on '$slug' from version '$current_version' to '$latest_version'"

    # Update updater.json or create it
    if [ -f "$updater_file" ]; then
      jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
         '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
         '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
      mv "$updater_file.tmp" "$updater_file"
    else
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
         '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file"
    fi

    # Update config.json version (only if not 'latest')
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    # Ensure CHANGELOG.md exists and append update entry
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      log "$COLOR_YELLOW" "Created new CHANGELOG.md for $slug"
    fi

    {
      echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))"
      echo ""
      echo "    Updated from $current_version to $latest_version"
      echo ""
    } >> "$changelog_file"

    log "$COLOR_GREEN" "CHANGELOG.md updated for $slug"

  else
    log "$COLOR_BLUE" "Add-on '$slug' is already up-to-date ✔"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done
}

LAST_RUN_FILE="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')"

# Run once on start
perform_update_check

echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

while true; do
  NOW_TIME=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=""

  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$NOW_TIME" = "$CHECK_TIME" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_TIME on $TODAY"
    perform_update_check
    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."
    sleep 60
  else
    log "$COLOR_BLUE" "📅 Next check scheduled at $CHECK_TIME"
  fi

  sleep 60
done
