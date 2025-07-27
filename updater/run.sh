#!/usr/bin/env bash
set -eo pipefail

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LAST_RUN_FILE="/data/last_run_date.txt"

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "[$(date '+%H:%M:%S')] ${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "❌ ERROR: Missing config file: $CONFIG_PATH"
  exit 1
fi

# Load config
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron // "0 7 * * *"' "$CONFIG_PATH") # Default: 07:00 daily

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Cron match
cron_matches_now() {
  local cron="$1"
  local minute hour dom month dow
  IFS=' ' read -r minute hour dom month dow <<< "$cron"

  local now_minute=$(date +%M)
  local now_hour=$(date +%H)
  local now_dom=$(date +%d)
  local now_month=$(date +%m)
  local now_dow=$(date +%u) # 1=Mon

  [[ "$minute" == "*" || "$minute" == "$now_minute" ]] &&
  [[ "$hour" == "*" || "$hour" == "$now_hour" ]] &&
  [[ "$dom" == "*" || "$dom" == "$now_dom" ]] &&
  [[ "$month" == "*" || "$month" == "$now_month" ]] &&
  [[ "$dow" == "*" || "$dow" == "$now_dow" ]]
}

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_YELLOW" "📦 Cloning repository..."
    git clone "$GIT_AUTH_REPO" "$REPO_DIR"
  else
    log "$COLOR_YELLOW" "📥 Pulling latest changes..."
    cd "$REPO_DIR"
    git reset --hard
    git clean -fd
    git pull origin main
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local url=""
  if [[ "$image" == *"ghcr.io"* ]]; then
    url="https://ghcr.io/v2/${image#ghcr.io/}/tags/list"
    curl -s "$url" | jq -r '.tags[]' | sort -Vr | head -n1
  elif [[ "$image" == *"linuxserver"* ]]; then
    repo="${image#*/}"
    url="https://hub.docker.com/v2/repositories/linuxserver/$repo/tags?page_size=1"
    curl -s "$url" | jq -r '.results[0].name'
  else
    repo="${image#*/}"
    url="https://hub.docker.com/v2/repositories/${repo}/tags?page_size=1"
    curl -s "$url" | jq -r '.results[0].name'
  fi
}

update_addon_if_needed() {
  local addon_dir="$1"
  local config_file="$addon_dir/config.json"

  if [ ! -f "$config_file" ]; then
    log "$COLOR_RED" "⚠️ Missing config.json in $addon_dir"
    return
  fi

  local image=$(jq -r '.image // empty' "$config_file")
  local current_version=$(jq -r '.version // "unknown"' "$config_file")
  local latest_tag=$(get_latest_docker_tag "$image")

  if [[ -z "$latest_tag" || "$latest_tag" == "null" ]]; then
    log "$COLOR_RED" "❌ Could not fetch latest tag for $image"
    return
  fi

  if [ "$current_version" != "$latest_tag" ]; then
    log "$COLOR_YELLOW" "⬆️  Update available in $addon_dir: $current_version → $latest_tag"
    jq --arg version "$latest_tag" '.version = $version' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    local today=$(date '+%d-%m-%Y')
    echo "{\"last_update\": \"$today\"}" > "$addon_dir/updater.json"

    local changelog_file="$addon_dir/CHANGELOG.md"
    local changelog_entry="## 🔄 $latest_tag ($today)\n\n- ✨ Auto-updated by updater\n"
    echo -e "$changelog_entry\n$(cat "$changelog_file" 2>/dev/null)" > "$changelog_file"

    cd "$REPO_DIR"
    git add "$addon_dir/config.json" "$addon_dir/updater.json" "$changelog_file"
    git commit -m "⬆️ Update $addon_dir to $latest_tag"
    
    for attempt in {1..3}; do
      if git push origin main; then
        log "$COLOR_GREEN" "🚀 Pushed update for $addon_dir"
        break
      else
        log "$COLOR_YELLOW" "🔁 Retry git push $attempt..."
        sleep 5
      fi
    done
  else
    log "$COLOR_BLUE" "✅ $addon_dir is up to date ($current_version)"
  fi
}

perform_update_check() {
  clone_or_update_repo
  for dir in "$REPO_DIR"/*/; do
    [ -d "$dir" ] || continue
    update_addon_if_needed "$dir"
  done
}

# 🚀 Initial Start
log "$COLOR_GREEN" "🚀 HomeAssistant Add-on Updater started"
perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

# 🕒 Main cron-style loop
while true; do
  NOW=$(date +%Y-%m-%d)
  LAST_RUN=$(cat "$LAST_RUN_FILE" 2>/dev/null || echo "")

  if cron_matches_now "$CHECK_CRON" && [ "$NOW" != "$LAST_RUN" ]; then
    log "$COLOR_GREEN" "🕓 Running scheduled check: $(date '+%H:%M')"
    perform_update_check
    echo "$NOW" > "$LAST_RUN_FILE"
  fi
  sleep 30
done
