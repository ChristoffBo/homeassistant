#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE=/data/updater.log

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

# Clear log file on start
> "$LOG_FILE"

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_DARK_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIMES=$(jq -r '.check_times // .check_time' "$CONFIG_PATH")  # Accepts comma-separated or single time

GITHUB_AUTH_HEADER=""
if [ -n "$GITHUB_TOKEN" ]; then
  GITHUB_AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"
fi

# Convert single time to array, or comma-separated string to array
IFS=',' read -r -a CHECK_TIMES_ARRAY <<< "$CHECK_TIMES"

declare -A LAST_RUN_TIMES  # Track last run date per check time

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
    git reset --hard HEAD
    git clean -fd
    git pull
    log "$COLOR_GREEN" "Repository updated."
  fi
}

# [Include all your other helper functions here (fetch_latest_dockerhub_tag, update_addon_if_needed, etc.) exactly as before...]

# For brevity, let's assume all helper functions are here exactly as before
# Including get_latest_docker_tag, update_addon_if_needed, perform_update_check, etc.

perform_update_check() {
  clone_or_update_repo

  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done
}

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')"
perform_update_check

while true; do
  NOW_TIME=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  RAN=false

  for CHECK_TIME in "${CHECK_TIMES_ARRAY[@]}"; do
    # Trim whitespace (if any)
    CHECK_TIME=$(echo "$CHECK_TIME" | xargs)

    if [ "$NOW_TIME" = "$CHECK_TIME" ]; then
      # Check if already ran for this time today
      if [ "${LAST_RUN_TIMES[$CHECK_TIME]}" != "$TODAY" ]; then
        log "$COLOR_GREEN" "⏰ Running scheduled update check for $CHECK_TIME at $NOW_TIME"
        perform_update_check
        LAST_RUN_TIMES[$CHECK_TIME]="$TODAY"
        RAN=true
      else
        log "$COLOR_YELLOW" "Skipping duplicate run for $CHECK_TIME on $TODAY"
      fi
    fi
  done

  if [ "$RAN" = false ]; then
    log "$COLOR_BLUE" "No scheduled update at $NOW_TIME. Waiting..."
  fi

  sleep 60
done
