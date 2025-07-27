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
COLOR_DARK_RED="\033[0;31m"  # Dark red for errors

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}"
}

# Clear the log file at the start of the script
> "$LOG_FILE"

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_DARK_RED" "ERROR: Config file $CONFIG_PATH not found!" | tee -a "$LOG_FILE"
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
  log "$COLOR_BLUE" "Checking repository: $GITHUB_REPO" | tee -a "$LOG_FILE"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "Repository not found locally. Cloning..." | tee -a "$LOG_FILE"
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"
    else
      git clone "$GITHUB_REPO" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"
    fi
    log "$COLOR_GREEN" "Repository cloned successfully." | tee -a "$LOG_FILE"
  else
    log "$COLOR_BLUE" "Repository found. Pulling latest changes..." | tee -a "$LOG_FILE"
    cd "$REPO_DIR"
    git pull 2>&1 | tee -a "$LOG_FILE"
    log "$COLOR_GREEN" "Repository updated." | tee -a "$LOG_FILE"
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

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "No config.json or build.json found in $addon_path, skipping." | tee -a "$LOG_FILE"
    return
  fi

  local image=""

  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file")
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "Addon '$(basename "$addon_path")' has no Docker image defined, skipping." | tee -a "$LOG_FILE"
    return
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file")
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file")
  fi

  log "$COLOR_BLUE" "----------------------------" | tee -a "$LOG_FILE"
  log "$COLOR_BLUE" "Addon: $slug" | tee -a "$LOG_FILE"
  log "$COLOR_BLUE" "Current Docker version: $upstream_version" | tee -a "$LOG_FILE"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "WARNING: Could not fetch latest docker tag for image $image" | tee -a "$LOG_FILE"
    log "$COLOR_BLUE" "Latest Docker version:  WARNING: Could not fetch" | tee -a "$LOG_FILE"
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔" | tee -a "$LOG_FILE"
    log "$COLOR_BLUE" "----------------------------" | tee -a "$LOG_FILE"
    return
  fi

  log "$COLOR_BLUE" "Latest Docker version:  $latest_version" | tee -a "$LOG_FILE"

  if [ "$latest_version" != "$upstream_version" ]; then
    log "$COLOR_GREEN" "Update available: $upstream_version -> $latest_version" | tee -a "$LOG_FILE"

    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true

    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    if [ ! -f "$changelog_file" ]; then
      touch "$changelog_file"
      log "$COLOR_YELLOW" "Created new CHANGELOG.md" | tee -a "$LOG_FILE"
    fi

    {
      echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))"
      echo ""
      echo "    Update to latest version from $image"
      echo ""
    } >> "$changelog_file"

    log "$COLOR_GREEN" "CHANGELOG.md updated." | tee -a "$LOG_FILE"
  else
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔" | tee -a "$LOG_FILE"
  fi

  log "$COLOR_BLUE" "----------------------------" | tee -a "$LOG_FILE"
}

perform_update_check() {
  clone_or_update_repo
  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done
}

# Main loop variables
LAST_MINUTE_LOGGED=""

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')" | tee -a "$LOG_FILE"
perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

while true; do
  NOW_HOUR=$(date +%H)
  NOW_MIN=$(date +%M)
  NOW_TOTAL=$((10#$NOW_HOUR * 60 + 10#$NOW_MIN))

  CHECK_HOUR=${CHECK_TIME%%:*}
  CHECK_MIN=${CHECK_TIME##*:}
  CHECK_TOTAL=$((10#$CHECK_HOUR * 60 + 10#$CHECK_MIN))

  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=""
  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  # Log Now message once per minute
  CURRENT_MINUTE="${NOW_HOUR}:${NOW_MIN}"
  if [ "$CURRENT_MINUTE" != "$LAST_MINUTE_LOGGED" ]; then
    log "$COLOR_BLUE" "Now: ${NOW_HOUR}:${NOW_MIN}, Check time: $CHECK_TIME, Last run: $LAST_RUN, Today: $TODAY" | tee -a "$LOG_FILE"
    LAST_MINUTE_LOGGED="$CURRENT_MINUTE"
  fi

  if [ "$NOW_TOTAL" -ge "$CHECK_TOTAL" ] && [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_HOUR:$NOW_MIN on $TODAY" | tee -a "$LOG_FILE"
    perform_update_check
    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete." | tee -a "$LOG_FILE"
    sleep 60  # prevent multiple runs in the same minute
  else
    log "$COLOR_BLUE" "Waiting for next scheduled check..." | tee -a "$LOG_FILE"
  fi

  sleep 60
done
