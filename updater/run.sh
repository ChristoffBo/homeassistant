#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_DARK_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_DARK_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

# GitHub API auth header if token provided
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
    git reset --hard
    git clean -fd
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

generate_changelog() {
  local addon_path="$1"
  local image="$2"
  local version="$3"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$changelog_file" ]; then
    touch "$changelog_file"
    log "$COLOR_YELLOW" "Created new CHANGELOG.md for $(basename "$addon_path")"
  fi

  {
    echo "v$version ($(date +'%d-%m-%Y %H:%M'))"
    echo ""
    echo "    Update to latest version from $image"
    echo ""
  } >> "$changelog_file"

  log "$COLOR_GREEN" "CHANGELOG.md updated for $(basename "$addon_path")"
}

update_updater_json() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"

  local slug=$(jq -r '.slug // empty' "$config_file" || echo "")
  local image=$(jq -r '.image // empty' "$config_file" || echo "")
  local version=$(jq -r '.version // empty' "$config_file" || echo "")
  local datetime=$(date +'%d-%m-%Y %H:%M')

  jq -n --arg slug "$slug" --arg image "$image" --arg v "$version" --arg dt "$datetime" \
    '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file"

  log "$COLOR_GREEN" "updater.json updated for $slug"
}

update_addons() {
  for addon_path in "$REPO_DIR"/*/; do
    [ -f "$addon_path/config.json" ] || continue

    local addon_name
    addon_name=$(basename "$addon_path")

    image=$(jq -r '.image' "$addon_path/config.json")
    if [ -z "$image" ] || [ "$image" == "null" ]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$addon_name' has no image defined, skipping."
      continue
    fi

    latest_tag=$(get_latest_docker_tag "$image")
    if [ -z "$latest_tag" ]; then
      log "$COLOR_DARK_RED" "❌ Failed to fetch latest tag for add-on '$addon_name' (image: $image)"
      continue
    fi

    current_version=$(jq -r '.version' "$addon_path/config.json" || echo "")
    if [ "$latest_tag" != "$current_version" ]; then
      log "$COLOR_GREEN" "🔄 Updating add-on '$addon_name' from version '$current_version' to '$latest_tag'"
      jq --arg ver "$latest_tag" '.version = $ver' "$addon_path/config.json" > "$addon_path/config.tmp" && mv "$addon_path/config.tmp" "$addon_path/config.json"
      generate_changelog "$addon_path" "$image" "$latest_tag"
      update_updater_json "$addon_path"
    else
      log "$COLOR_BLUE" "✔ Add-on '$addon_name' is already up-to-date (version: $current_version)"
    fi
  done
}

perform_update_check() {
  clone_or_update_repo
  update_addons
}

LAST_RUN_FILE="/data/last_run_date.txt"

# Clear log on start
: > /data/updater.log

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

  if [ "$NOW_TIME" = "$CHECK_TIME" ]; then
    if [ "$LAST_RUN" != "$TODAY" ]; then
      log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_TIME on $TODAY"
      perform_update_check
      echo "$TODAY" > "$LAST_RUN_FILE"
      log "$COLOR_GREEN" "✅ Scheduled update checks complete."
    else
      log "$COLOR_YELLOW" "⚠️ Update already run today at $LAST_RUN"
    fi
    sleep 60 # avoid running multiple times in the same minute
  else
    # Calculate next check time for logging
    CHECK_HOUR=${CHECK_TIME%%:*}
    CHECK_MIN=${CHECK_TIME##*:}
    CURRENT_SEC=$(date +%s)
    TODAY_SEC=$(date -d "$(date +%Y-%m-%d)" +%s 2>/dev/null || echo 0)

    if [ "$TODAY_SEC" -ne 0 ]; then
      CHECK_SEC=$((TODAY_SEC + CHECK_HOUR * 3600 + CHECK_MIN * 60))
      if [ "$CURRENT_SEC" -ge "$CHECK_SEC" ]; then
        TOMORROW_SEC=$((TODAY_SEC + 86400))
        NEXT_CHECK_TIME=$(date -d "@$((TOMORROW_SEC + CHECK_HOUR * 3600 + CHECK_MIN * 60))" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
      else
        NEXT_CHECK_TIME=$(date -d "@$CHECK_SEC" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
      fi
    else
      NEXT_CHECK_TIME="$CHECK_TIME (date command not supported)"
    fi

    log "$COLOR_BLUE" "📅 Next check scheduled at $NEXT_CHECK_TIME"
    sleep 60
  fi
done
