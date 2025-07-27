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
  log "$COLOR_RED" "❌ ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")

if [ -z "$CHECK_CRON" ] || [ "$CHECK_CRON" == "null" ]; then
  log "$COLOR_RED" "❌ ERROR: 'check_cron' is not set in $CONFIG_PATH"
  exit 1
fi

# Ensure .git suffix
if [[ "$GITHUB_REPO" != *.git ]]; then
  GITHUB_REPO="${GITHUB_REPO}.git"
fi

LOG_FILE="/data/updater.log"
: > "$LOG_FILE"

clone_or_update_repo() {
  log "$COLOR_BLUE" "📥 Pulling latest changes from $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "📂 Repository not found locally. Cloning..."
    git clone "$GITHUB_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository cloned successfully."
  else
    log "$COLOR_BLUE" "🔄 Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull origin main >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository updated."
  fi
}

# (Same fetch_latest_dockerhub_tag, fetch_latest_linuxserver_tag, fetch_latest_ghcr_tag, get_latest_docker_tag functions as before)

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json — skipping."
    return
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    [[ "$arch" == "x86_64" ]] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined — skipping."
    return
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  [[ -z "$slug" || "$slug" == "null" ]] && slug=$(basename "$addon_path")

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🔎 Checking add-on: $slug"
  log "$COLOR_BLUE" "📦 Current version: $current_version"
  log "$COLOR_BLUE" "🖼️ Image: $image"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  [[ -z "$latest_version" || "$latest_version" == "null" ]] && latest_version="latest"

  log "$COLOR_BLUE" "🌐 Latest available version: $latest_version"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️ Updating add-on '$slug' from '$current_version' to '$latest_version'"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    mv "$config_file.tmp" "$config_file"

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
    Update from $current_version to $latest_version (image: $image)

"

    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "📄 CHANGELOG.md updated for $slug"
  else
    log "$COLOR_BLUE" "✔ Add-on '$slug' is already up-to-date"
  fi
  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updated=0
  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path" && updated=$((updated+1))
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Automatic update: bump addon versions" >> "$LOG_FILE" 2>&1 || true

    if git push origin main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed. Check your authentication and remote URL."
    fi
  else
    log "$COLOR_BLUE" "ℹ️ No changes to commit."
  fi
}

last_run_file="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Add-on Updater started at $(date '+%d-%m-%Y %H:%M')"

# Run update immediately on startup
perform_update_check
echo "$(date +%Y-%m-%d)" > "$last_run_file"

while true; do
  # Parse cron string: expect "min hour * * *"
  cron_minute=$(echo "$CHECK_CRON" | awk '{print $1}')
  cron_hour=$(echo "$CHECK_CRON" | awk '{print $2}')

  if ! [[ "$cron_minute" =~ ^[0-9]+$ ]] || ! [[ "$cron_hour" =~ ^[0-9]+$ ]]; then
    log "$COLOR_RED" "❌ ERROR: Unsupported or invalid cron expression: $CHECK_CRON"
    exit 1
  fi

  NOW_HOUR=$(date +%H)
  NOW_MIN=$(date +%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=""

  if [ -f "$last_run_file" ]; then
    LAST_RUN=$(cat "$last_run_file")
  fi

  if [ "$NOW_HOUR" -eq "$cron_hour" ] && [ "$NOW_MIN" -eq "$cron_minute" ] && [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_HOUR:$NOW_MIN on $TODAY"
    perform_update_check
    echo "$TODAY" > "$last_run_file"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."
    sleep 60
  else
    # Try to show next run time or fallback unknown
    next_run_time=$(date -d "today $cron_hour:$cron_minute" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "unknown")
    log "$COLOR_BLUE" "📅 Next check scheduled at $next_run_time"
  fi

  sleep 30
done
