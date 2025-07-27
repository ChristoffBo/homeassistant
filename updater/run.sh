#!/usr/bin/env bash
set -euo pipefail
trap 'echo "❌ Error occurred at line $LINENO"' ERR

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
  local timestamp
  timestamp=$(date '+[%H:%M:%S]')
  echo -e "${timestamp} ${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "❌ ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron // empty' "$CONFIG_PATH")

if [ -z "$CHECK_CRON" ]; then
  log "$COLOR_RED" "❌ ERROR: 'check_cron' is not set in $CONFIG_PATH"
  exit 1
fi

# Prepare authenticated repo URL only if username and token are set
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  # Insert credentials for git auth
  AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
else
  AUTH_REPO="$GITHUB_REPO"
fi

# Clear log file before each run
LOG_FILE="/data/updater.log"
: > "$LOG_FILE"

clone_or_update_repo() {
  log "$COLOR_BLUE" "📥 Pulling latest changes from $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "🛠️ Repository not found locally. Cloning..."
    git clone "$AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository cloned successfully."
  else
    log "$COLOR_BLUE" "🔄 Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull "$AUTH_REPO" main >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository updated."
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=10&ordering=last_updated"
  local tags_json
  tags_json=$(curl -s "$url")
  local tag
  tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | head -n 1)
  if [ -n "$tag" ]; then
    echo "$tag"
  else
    echo "latest"
  fi
}

fetch_latest_linuxserver_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local tag
  tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
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
  local tags_json
  tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null)
  local tag
  tag=$(echo "$tags_json" | jq -r '.tags[-1]' 2>/dev/null)
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
    fetch_latest_linuxserver_tag "$image_no_tag"
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    fetch_latest_ghcr_tag "$image_no_tag"
  else
    fetch_latest_dockerhub_tag "$image_no_tag"
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch
    arch=$(uname -m)
    [[ "$arch" == "x86_64" ]] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
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
  log "$COLOR_BLUE" "📦 Current version: $current_version"
  log "$COLOR_BLUE" "🐳 Docker image: $image"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  log "$COLOR_BLUE" "🔍 Latest version available: $latest_version"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "🔄 Updating add-on '$slug' from version '$current_version' to '$latest_version'"

    # Update config.json version
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    # Update updater.json
    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M:%S')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M:%S')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    # Ensure CHANGELOG.md exists and prepend changelog
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "📄 Created new CHANGELOG.md for $slug"
    fi

    local NEW_ENTRY
    NEW_ENTRY="\
v$latest_version ($(date +'%d-%m-%Y %H:%M:%S'))
    Update from version $current_version to $latest_version (image: $image)

"

    # Prepend new entry after header (2 lines)
    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

  else
    log "$COLOR_BLUE" "✔️ Add-on '$slug' is already up-to-date"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  # Set git user config if missing
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updated=0

  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path" && updated=$((updated+1))
  done

  # Commit and push changes if any
  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Automatic update: bump addon versions" >> "$LOG_FILE" 2>&1 || true

    if git push "$AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "🚀 Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed. Check your authentication and remote URL."
    fi
  else
    log "$COLOR_BLUE" "ℹ️ No changes to commit."
  fi
}

get_next_cron_time() {
  # Just echo the cron schedule since calculating next run time from cron expression
  # is non-trivial in bash without extra tools.
  echo "$CHECK_CRON"
}

LAST_RUN_FILE="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Add-on Updater started at $(date '+%d-%m-%Y %H:%M:%S')"

# Run first update on startup
perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

while true; do
  # Calculate next run time (just show the cron expression)
  local next_run
  next_run=$(get_next_cron_time)
  log "$COLOR_BLUE" "📅 Next check scheduled at $next_run (cron expression)"

  # Sleep and check every 60 seconds whether to run updates
  sleep 60

  # To actually trigger at cron schedule, you'd need to parse cron expression and current time,
  # or rely on external cron or scheduler, but this script just logs and runs daily by date check.

  # Run daily check at midnight (simplified)
  local today
  today=$(date +%Y-%m-%d)
  local last_run=""
  if [ -f "$LAST_RUN_FILE" ]; then
    last_run=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$today" != "$last_run" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks for $today"
    perform_update_check
    echo "$today" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."
  else
    log "$COLOR_BLUE" "💤 No update needed today."
  fi

  log "$COLOR_BLUE" "💓 Updater running, sleeping 60 seconds..."
done
