#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

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
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

GITHUB_AUTH_HEADER=""
if [ -n "$GITHUB_TOKEN" ]; then
  GITHUB_AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"
fi

clone_or_update_repo() {
  log "$COLOR_BLUE" "Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "Repository not found locally. Cloning..."
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR"
    else
      git clone "$GITHUB_REPO" "$REPO_DIR"
    fi
    log "$COLOR_GREEN" "Repository cloned successfully."
  else
    log "$COLOR_BLUE" "Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull
    log "$COLOR_GREEN" "Repository updated."
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local retries=3
  local count=0
  local tag=""
  while [ $count -lt $retries ]; do
    tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
    if [ -n "$tag" ] && [ "$tag" != "null" ]; then
      echo "$tag"
      return 0
    fi
    count=$((count+1))
    sleep $((count * 2))
  done
  echo ""
}

fetch_latest_linuxserver_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
  if [ -n "$tag" ] && [ "$tag" != "null" ]; then
    echo "$tag"
  else
    echo ""
  fi
}

fetch_latest_ghcr_tag() {
  local image="$1"
  local repo_path="${image#ghcr.io/}"
  local url="https://ghcr.io/v2/${repo_path}/tags/list"
  local tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null)
  local tag=$(echo "$tags_json" | jq -r '.tags[-1]' 2>/dev/null)
  if [ -n "$tag" ] && [ "$tag" != "null" ]; then
    echo "$tag"
  else
    echo ""
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"
  if [[ "$image_no_tag" == linuxserver/* ]]; then
    echo "$(fetch_latest_linuxserver_tag "$image_no_tag")"
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    echo "$(fetch_latest_ghcr_tag "$image_no_tag")"
  else
    echo "$(fetch_latest_dockerhub_tag "$image_no_tag")"
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ]; then
    log "$COLOR_YELLOW" "No config.json found in $addon_path, skipping."
    return
  fi

  local image=""

  # Try build.json first for image
  if [ -f "$build_file" ]; then
    image=$(jq -r '.image // empty' "$build_file" 2>/dev/null || echo "")
  fi
  # If empty, try config.json
  if [ -z "$image" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null || echo "")
  fi

  if [ -z "$image" ]; then
    log "$COLOR_YELLOW" "Addon at $addon_path has no Docker image defined, skipping."
    return
  fi

  if [ ! -f "$updater_file" ]; then
    log "$COLOR_YELLOW" "updater.json missing for addon at $addon_path, creating."
    jq -n --arg slug "$(basename "$addon_path")" --arg image "$image" --argjson upstream_version '""' --arg last_update "" \
      '{slug: $slug, image: $image, upstream_version: $upstream_version, last_update: $last_update}' > "$updater_file"
  fi

  local slug upstream_version
  slug=$(jq -r '.slug // empty' "$updater_file")
  upstream_version=$(jq -r '.upstream_version // empty' "$updater_file")

  if [ -z "$slug" ]; then
    slug=$(basename "$addon_path")
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "Addon: $slug"
  log "$COLOR_BLUE" "Current Docker version: $upstream_version"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "WARNING: Could not fetch latest docker tag for image $image"
    log "$COLOR_BLUE" "Latest Docker version:  WARNING: Could not fetch"
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "Latest Docker version:  $latest_version"

  # Ensure version prefix v
  if [[ "$latest_version" != v* ]]; then
    latest_version="v$latest_version"
  fi

  # Current version from config.json version field
  local current_version
  current_version=$(jq -r '.version // empty' "$config_file")

  if [ "$latest_version" != "$current_version" ]; then
    log "$COLOR_GREEN" "Update available: $current_version -> $latest_version"

    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    if [ ! -f "$changelog_file" ]; then
      touch "$changelog_file"
      log "$COLOR_YELLOW" "Created new CHANGELOG.md"
    fi

    {
      echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))"
      echo ""
      echo "    Update to latest version from $image"
      echo ""
    } >> "$changelog_file"

    log "$COLOR_GREEN" "CHANGELOG.md updated."
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

LAST_RUN_FILE="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')"
perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

while true; do
  NOW_TIME=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=""

  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$NOW_TIME" = "$CHECK_TIME" ] && [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_TIME on $TODAY"
    perform_update_check
    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."
    sleep 60  # prevent multiple runs in same minute
  else
    next_check=$(date -d "tomorrow $CHECK_TIME" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "unknown")
    log "$COLOR_BLUE" "📅 Next check scheduled at $CHECK_TIME tomorrow ($next_check)"
  fi

  sleep 30
done
