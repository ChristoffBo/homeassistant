#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  # Print with timestamp and color + emoji
  echo -e "[$(date '+%H:%M:%S')] ${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "❌ ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM, e.g., "03:00"

# Prepare authenticated repo URL if credentials provided
GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  # Insert credentials into repo URL for push/pull auth (supports https:// only)
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Clear log file before each run
: > "$LOG_FILE"

clone_or_update_repo() {
  log "$COLOR_BLUE" "📥 Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "📂 Repository not found locally. Cloning..."
    git clone "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository cloned successfully."
  else
    log "$COLOR_BLUE" "🔄 Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository updated."
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=10&ordering=last_updated"
  local tags_json=$(curl -s "$url")
  local tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | head -n 1)
  if [ -n "$tag" ]; then
    echo "$tag"
  else
    echo "latest"
  fi
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

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json. Skipping."
    return
  fi

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
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined. Skipping."
    return
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Add-on: $slug"
  log "$COLOR_BLUE" "🔖 Current version: $current_version"
  log "$COLOR_BLUE" "🐳 Docker image: $image"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  log "$COLOR_BLUE" "⬆️ Latest version available: $latest_version"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "🔄 Updating add-on '$slug' from version '$current_version' to '$latest_version'"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "📝 Created new CHANGELOG.md for $slug"
    fi

    NEW_ENTRY="\
v$latest_version ($(date +'%d-%m-%Y %H:%M'))
    Update from version $current_version to $latest_version (image: $image)

"

    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "📝 CHANGELOG.md updated for $slug"

  else
    log "$COLOR_BLUE" "✅ Add-on '$slug' is already up-to-date."
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updated=0
  local addon_count=0

  for addon_path in "$REPO_DIR"/*/; do
    ((addon_count++))
    log "$COLOR_YELLOW" "🔍 Checking addon #$addon_count: $(basename "$addon_path")"
    update_addon_if_needed "$addon_path" && updated=$((updated+1))
  done

  log "$COLOR_BLUE" "ℹ️ Total addons checked: $addon_count"
  log "$COLOR_GREEN" "✅ Total addons updated: $updated"

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "Automatic update: bump addon versions" >> "$LOG_FILE" 2>&1 || true

    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "🚀 Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed. Check your authentication and remote URL."
    fi
  else
    log "$COLOR_BLUE" "ℹ️ No changes to commit."
  fi
}

LAST_RUN_FILE="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M:%S')"
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
    sleep 60
  else
    # Calculate next run time display
    CURRENT_SEC=$(date +%s)
    CHECK_HOUR=${CHECK_TIME%%:*}
    CHECK_MIN=${CHECK_TIME##*:}
    TODAY_SEC=$(date -d "$(date +%Y-%m-%d)" +%s 2>/dev/null || echo 0)
    if [ "$TODAY_SEC" -eq 0 ]; then
      NEXT_CHECK_TIME="$CHECK_TIME (date command unsupported)"
    else
      CHECK_SEC=$((TODAY_SEC + CHECK_HOUR * 3600 + CHECK_MIN * 60))
      if [ "$CURRENT_SEC" -ge "$CHECK_SEC" ]; then
        TOMORROW_SEC=$((TODAY_SEC + 86400))
        NEXT_CHECK_TIME=$(date -d "@$((TOMORROW_SEC + CHECK_HOUR * 3600 + CHECK_MIN * 60))" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
      else
        NEXT_CHECK_TIME=$(date -d "@$CHECK_SEC" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
      fi
    fi
    log "$COLOR_BLUE" "📅 Next check scheduled at $NEXT_CHECK_TIME"
  fi

  sleep 60
done
