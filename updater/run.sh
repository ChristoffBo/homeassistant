#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
LAST_RUN_FILE="/data/last_run.json"

# Colors
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_DARK_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

clear_log() {
  : > "$LOG_FILE"
}

load_config() {
  GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
  GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
  GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
  CHECK_TIME=$(jq -r '.check_time // "04:00"' "$CONFIG_PATH")
}

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_YELLOW" "Cloning repository..."
    AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
    git clone "$AUTH_REPO" "$REPO_DIR"
  else
    cd "$REPO_DIR"
    git reset --hard
    git clean -fd
    if ! git pull --rebase; then
      log "$COLOR_DARK_RED" "⚠️ Git pull failed. Please commit or stash local changes first."
    else
      log "$COLOR_GREEN" "✅ Repository updated"
    fi
  fi
}

fetch_latest_docker_tag() {
  local image="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$image/tags?page_size=1&ordering=last_updated"
  curl -s "$url" | jq -r '.results[0].name'
}

generate_changelog() {
  local addon="$1"
  local image="$2"
  local latest_tag="$3"
  local changelog_file="$addon/CHANGELOG.txt"

  echo -e "v$latest_tag ($(date +'%d-%m-%Y'))\n" \
    "Update to latest version from $image (changelog: https://github.com/${image/docker-${addon##*/}}/releases)\n" >> "$changelog_file"
}

update_updater_json() {
  local addon="$1"
  local updated_date=$(date +'%d-%m-%Y')
  echo "{\"last_update\": \"$updated_date\"}" > "$addon/updater.json"
}

update_addons() {
  for addon_path in "$REPO_DIR"/*/; do
    [ -f "$addon_path/config.json" ] || continue
    image=$(jq -r '.image' "$addon_path/config.json")
    [ -n "$image" ] && [ "$image" != "null" ] || continue

    latest_tag=$(fetch_latest_docker_tag "$image")
    if [ -n "$latest_tag" ]; then
      log "$COLOR_GREEN" "🔁 Updating ${addon_path##*/} to $latest_tag"
      jq --arg ver "$latest_tag" '.version = $ver' "$addon_path/config.json" > "$addon_path/config.tmp" && mv "$addon_path/config.tmp" "$addon_path/config.json"
      generate_changelog "$addon_path" "$image" "$latest_tag"
      update_updater_json "$addon_path"
    else
      log "$COLOR_DARK_RED" "❌ Failed to fetch tag for $image"
    fi
  done
}

should_run_now() {
  local now_time=$(date +%H:%M)
  local today=$(date +%Y-%m-%d)

  if [ ! -f "$LAST_RUN_FILE" ]; then return 0; fi

  local last_time=$(jq -r '.last_time' "$LAST_RUN_FILE")
  local last_date=$(jq -r '.last_date' "$LAST_RUN_FILE")

  [[ "$now_time" == "$CHECK_TIME" && "$last_date" != "$today" ]]
}

record_run() {
  echo "{\"last_time\": \"$(date +%H:%M)\", \"last_date\": \"$(date +%Y-%m-%d)\"}" > "$LAST_RUN_FILE"
}

run_update() {
  clear_log
  log "$COLOR_BLUE" "🧽 Log cleared"
  load_config
  clone_or_update_repo
  update_addons
  record_run
  log "$COLOR_GREEN" "✅ Update completed at $(date +%H:%M)"
}

# MAIN LOOP
while true; do
  load_config
  now=$(date +%H:%M)
  today=$(date +%Y-%m-%d)

  if should_run_now; then
    run_update
  fi

  sleep 60
done
