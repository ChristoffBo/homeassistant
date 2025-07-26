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

# GitHub API auth header if token provided
GITHUB_AUTH_HEADER=""
if [ -n "$GITHUB_TOKEN" ]; then
  GITHUB_AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"
fi

clone_or_update_repo() {
  log "$COLOR_BLUE" "🔄 Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "📥 Repository not found locally. Cloning..."
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR"
    else
      git clone "$GITHUB_REPO" "$REPO_DIR"
    fi
    log "$COLOR_GREEN" "✅ Repository cloned successfully."
  else
    log "$COLOR_BLUE" "📡 Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull
    log "$COLOR_GREEN" "✅ Repository updated."
  fi
}

# ... [fetch functions unchanged] ...

update_addon_if_needed() {
  # ... [same logic] ...

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ No config.json or build.json found in $addon_path, skipping."
    return
  fi

  # ... [same logic] ...

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Addon at $addon_path has no Docker image defined, skipping."
    return
  fi

  # ... [same logic] ...

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "📦 Current Docker version: $upstream_version"

  # ... [same logic] ...

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "⚠️ WARNING: Could not fetch latest docker tag for image $image"
    log "$COLOR_BLUE" "📦 Latest Docker version:  ⚠️ Could not fetch"
    log "$COLOR_BLUE" "✔️ Addon '$slug' is already up-to-date"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "📦 Latest Docker version:  $latest_version"

  if [ "$latest_version" != "$upstream_version" ]; then
    log "$COLOR_GREEN" "⬆️ Update available: $upstream_version -> $latest_version"

    # ... [updating files logic] ...

    if [ ! -f "$changelog_file" ]; then
      touch "$changelog_file"
      log "$COLOR_YELLOW" "📝 Created new CHANGELOG.md"
    fi

    {
      echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))"
      echo ""
      echo "    Update to latest version from $image"
      echo ""
    } >> "$changelog_file"

    log "$COLOR_GREEN" "📝 CHANGELOG.md updated."
  else
    log "$COLOR_BLUE" "✔️ Addon '$slug' is already up-to-date"
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
    sleep 60  # prevent multiple runs in same minute
  else
    CURRENT_SEC=$(date +%s)
    CHECK_SEC=$(date -d "$CHECK_TIME" +%s 2>/dev/null || echo 0)

    if [ "$CURRENT_SEC" -ge "$CHECK_SEC" ]; then
      NEXT_CHECK_TIME=$(date -d "tomorrow $CHECK_TIME" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
    else
      NEXT_CHECK_TIME=$(date -d "today $CHECK_TIME" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
    fi

    log "$COLOR_BLUE" "📅 Next check scheduled at $NEXT_CHECK_TIME"
  fi

  sleep 21600
done
