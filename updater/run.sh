#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LAST_RUN_FILE="/data/last_run_date.txt"

# Colored output for better readability
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color=$1
  shift
  echo -e "${color}$*${COLOR_RESET}"
}

# Validate config file exists
if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Load config values once
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

# Helper: GitHub auth header
GITHUB_AUTH_HEADER=""
if [ -n "$GITHUB_TOKEN" ]; then
  GITHUB_AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"
fi

clone_or_update_repo() {
  log "$COLOR_BLUE" "Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "Cloning repository..."
    if [[ -n "$GITHUB_USERNAME" && -n "$GITHUB_TOKEN" ]]; then
      local auth_repo
      auth_repo=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$auth_repo" "$REPO_DIR"
    else
      git clone "$GITHUB_REPO" "$REPO_DIR"
    fi
    log "$COLOR_GREEN" "Repository cloned successfully."
  else
    log "$COLOR_BLUE" "Repository exists. Pulling latest changes..."
    (cd "$REPO_DIR" && git pull)
    log "$COLOR_GREEN" "Repository updated."
  fi
}

fetch_latest_dockerhub_tag() {
  local repo=$1
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local retries=3
  local count=0
  local tag=""
  while [ $count -lt $retries ]; do
    tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null || echo "")
    if [[ -n "$tag" && "$tag" != "null" ]]; then
      echo "$tag"
      return 0
    fi
    count=$((count+1))
    sleep $((count * 2))
  done
  echo ""
}

fetch_latest_linuxserver_tag() {
  local repo=$1
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null || echo "")
  [[ "$tag" == "null" ]] && tag=""
  echo "$tag"
}

fetch_latest_ghcr_tag() {
  local image=$1
  local repo_path="${image#ghcr.io/}"
  local url="https://ghcr.io/v2/${repo_path}/tags/list"
  local tags_json
  if [[ -n "$GITHUB_TOKEN" ]]; then
    tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null || echo "")
  else
    tags_json=$(curl -sSL "$url" 2>/dev/null || echo "")
  fi
  local tag
  tag=$(echo "$tags_json" | jq -r '.tags[-1]' 2>/dev/null || echo "")
  [[ "$tag" == "null" ]] && tag=""
  echo "$tag"
}

get_latest_docker_tag() {
  local image=$1
  local image_no_tag="${image%%:*}"

  if [[ "$image_no_tag" == linuxserver/* ]]; then
    fetch_latest_linuxserver_tag "$image_no_tag"
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    fetch_latest_ghcr_tag "$image_no_tag"
  else
    fetch_latest_dockerhub_tag "$image_no_tag"
  fi
}

update_addon_if_needed() {
  local addon_path=$1
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  # Determine Docker image from config.json or build.json
  local image=""
  if [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi
  if [[ -z "$image" && -f "$build_file" ]]; then
    image=$(jq -r '.image // empty' "$build_file")
  fi

  if [[ -z "$image" ]]; then
    log "$COLOR_YELLOW" "Addon at $addon_path has no Docker image defined, skipping."
    return
  fi

  # Create updater.json if missing
  if [ ! -f "$updater_file" ]; then
    log "$COLOR_YELLOW" "Creating missing updater.json for $addon_path"
    jq -n --arg slug "$(basename "$addon_path")" --arg image "$image" --argjson upstream_version '""' --arg last_update "" \
      '{slug: $slug, image: $image, upstream_version: $upstream_version, last_update: $last_update}' > "$updater_file"
  fi

  local slug upstream_version
  slug=$(jq -r '.slug // empty' "$updater_file")
  upstream_version=$(jq -r '.upstream_version // empty' "$updater_file")

  [[ -z "$slug" ]] && slug=$(basename "$addon_path")

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "Addon: $slug"
  l
