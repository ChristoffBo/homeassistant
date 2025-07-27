#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE=/data/updater.log

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_DARK_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Clear log at start
> "$LOG_FILE"

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO_RAW=$(jq -r '.github_repo' "$CONFIG_PATH")   # e.g. https://github.com/ChristoffBo/homeassistant
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

# Append '.git' suffix if missing
if [[ "$GITHUB_REPO_RAW" != *.git ]]; then
  GITHUB_REPO="${GITHUB_REPO_RAW}.git"
else
  GITHUB_REPO="$GITHUB_REPO_RAW"
fi

# Authenticated repo URL for git operations
AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")

clone_or_update_repo() {
  log "$COLOR_BLUE" "Checking repository: $GITHUB_REPO_RAW"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "Repository not found locally. Cloning..."
    git clone "$AUTH_REPO" "$REPO_DIR" && log "$COLOR_GREEN" "Repository cloned successfully." || { log "$COLOR_RED" "Git clone failed."; exit 1; }
  else
    log "$COLOR_BLUE" "Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git reset --hard
    git clean -fd
    git pull --rebase "$AUTH_REPO" && log "$COLOR_GREEN" "Repository updated." || { log "$COLOR_RED" "Git pull failed."; exit 1; }
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

  # Fix for lscr.io/linuxserver/ images to map to linuxserver/ on Docker Hub API
  if [[ "$image_no_tag" == lscr.io/linuxserver/* ]]; then
    image_no_tag="${image_no_tag#lscr.io/}"
  fi

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

  # Skip if neither config.json nor build.json found
  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "No config.json or build.json found in $addon_path, skipping."
    return
  fi

  local image=""
  local current_version=""
  local slug

  # Determine image & slug from build.json or config.json
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file")
    slug=$(jq -r '.slug // empty' "$build_file")
    current_version=$(jq -r '.version // empty' "$build_file")
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
    slug=$(jq -r '.slug // empty' "$config_file")
    current_version=$(jq -r '.version // empty' "$config_file")
  fi

  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "Add-on '$slug' has no Docker image defined, skipping."
    return
  fi

  # Read upstream_version from updater.json or empty if none
  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file")
  fi

  # Use current version if upstream_version is empty
  if [ -z "$upstream_version" ]; then
    upstream_version="$current_version"
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "Addon: $slug"
  log "$COLOR_BLUE" "Current version: $current_version"
  log "$COLOR_BLUE" "Image: $image"
  log "$COLOR_BLUE" "Latest version available: Checking..."

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "WARNING: Could not fetch latest docker tag for image $image"
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "Latest version available: $latest_version"

  if [ "$latest_version" != "$upstream_version" ]; then
    log "$COLOR_GREEN" "🔄 Updating add-on '$slug' from version '$upstream_version' to '$latest_version'"

    # Update or create updater.json
    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt | .slug = "'$slug'" | .image = "'$image'"' "$updater_file" 2>/dev/null > "$updater_file.tmp" || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    # Update version in config.json or build.json if version exists
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
      if [ -f "$config_file.tmp" ]; then
        mv "$config_file.tmp" "$config_file"
      fi
    fi

    if [ -f "$build_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$build_file" > "$build_file.tmp" 2>/dev/null || true
      if [ -f "$build_file.tmp" ]; then
        mv "$build_file.tmp" "$build_file"
      fi
    fi

    # Always create CHANGELOG.md if missing
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      log "$COLOR_YELLOW" "Created new CHANGELOG.md for $slug"
    fi

    # Append changelog entry
    {
      echo ""
      echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))"
      echo ""
      echo "    Update to latest version from $image"
      echo ""
    } >> "$changelog_file"

    log "$COLOR_GREEN" "CHANGELOG.md updated for $slug"
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

    # Commit and push changes if any
    cd "$REPO_DIR"
    if git diff --quiet && git diff --cached --quiet; then
      log "$COLOR_BLUE" "No changes to commit."
    else
      git add .
      git commit -m "Automatic update: bump addon versions"
      if git push "$AUTH_REPO" HEAD; then
        log "$COLOR_GREEN" "Git push successful."
      else
        log "$COLOR_RED" "Git push failed. Check authentication and remote URL."
      fi
    fi

    # Pull again to stay up to date
    if git pull --rebase "$AUTH_REPO"; then
      log "$COLOR_GREEN" "Git pull successful."
    else
      log "$COLOR_RED" "Git pull failed."
    fi
  else
    log "$COLOR_BLUE" "📅 Next check scheduled at $CHECK_TIME"
  fi

  sleep 60
done
