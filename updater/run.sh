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
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

LOG_FILE="/data/updater.log"
: > "$LOG_FILE"

# --- all the helper functions here (unchanged for brevity) ---
# clone_or_update_repo, fetch_latest_dockerhub_tag, etc.

# --- update_addon_if_needed (emoji enhanced) ---
update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️  Add-on '$(basename "$addon_path")' has no config.json or build.json, skipping."
    return
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    [ "$arch" = "x86_64" ] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️  Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
  fi

  local slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  [ -z "$slug" ] || [ "$slug" == "null" ] && slug=$(basename "$addon_path")

  local current_version=""
  [ -f "$config_file" ] && current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r "')

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")
  [ -z "$latest_version" ] || [ "$latest_version" == "null" ] && latest_version="latest"

  log "$COLOR_BLUE" "📦 Add-on: $slug"
  log "$COLOR_BLUE" "🔖 Current: $current_version"
  log "$COLOR_BLUE" "🛰️  Image: $image"
  log "$COLOR_BLUE" "🆕 Latest: $latest_version"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version → $latest_version"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "📝 Created CHANGELOG.md"
    fi

    NEW_ENTRY="\
v$latest_version ($(date +'%d-%m-%Y %H:%M'))
  🚀 Update from $current_version to $latest_version (image: $image)

"

    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "📘 CHANGELOG.md updated for $slug"
  else
    log "$COLOR_BLUE" "✅ $slug is already up-to-date"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

# --- perform_update_check (unchanged logic) ---
perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "🤖 Automatic update: bump addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "🚀 Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed. Check credentials or remote."
    fi
  else
    log "$COLOR_BLUE" "🔍 No changes to commit."
  fi
}

# --- Scheduler Loop ---
LAST_RUN_FILE="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Add-on Updater started at $(date '+%d-%m-%Y %H:%M')"
perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

log "$COLOR_BLUE" "🕒 Waiting for next check at $CHECK_TIME daily..."

while true; do
  NOW=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=$(cat "$LAST_RUN_FILE" 2>/dev/null || echo "")

  if [ "$NOW" == "$CHECK_TIME" ] && [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "⏰ Time matched ($NOW) – Running update check!"
    perform_update_check
    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Done. Next check: tomorrow."
    sleep 60
  fi

  sleep 30
done
