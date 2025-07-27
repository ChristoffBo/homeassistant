#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config
TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ

# Logging colors
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  echo -e "[\033[90m$(date '+%Y-%m-%d %H:%M:%S %Z')\033[0m] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

send_notification() {
  local message="$1"
  local type=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
  local url=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
  local token=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")

  if [[ -z "$type" || -z "$url" ]]; then
    return
  fi

  case "$type" in
    gotify)
      curl -s -X POST "$url/message" \
        -H "X-Gotify-Key: $token" \
        -F "title=Addon Updater" \
        -F "message=$message" \
        -F "priority=5" > /dev/null || true
      ;;
    mailrise)
      curl -s -X POST "$url" -H "Content-Type: text/plain" --data "$message" > /dev/null || true
      ;;
    apprise)
      curl -s "$url" -d "$message" > /dev/null || true
      ;;
    *)
      log "$COLOR_RED" "❌ Unknown notifier type: $type"
      ;;
  esac
}

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Cloning repository..."
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      exit 1
    fi
  else
    log "$COLOR_PURPLE" "🔄 Pulling latest changes from GitHub..."
    cd "$REPO_DIR"
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git pull successful."
    else
      log "$COLOR_RED" "❌ Git pull failed."
    fi
  fi
}

# Read GitHub info from config
GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron // "0 * * * *"' "$CONFIG_PATH")  # default hourly
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ="$TIMEZONE"

NOTIFIER_ENABLED=$(jq -r '.notifier.enabled // false' "$CONFIG_PATH")
NOTIFIER_TYPE=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
NOTIFIER_URL=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
NOTIFIER_TOKEN=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

UPDATE_SUMMARY=""
UPDATED=0

update_addon_if_needed() {
  local addon_path="$1"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local updater_file="$addon_path/updater.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  # Determine Docker image and version priority: config.json > build.json > updater.json
  local image=""
  local current_version=""

  if [[ -f "$config_file" ]]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null)
  fi

  if [[ -z "$image" || "$image" == "null" ]]; then
    if [[ -f "$build_file" ]]; then
      image=$(jq -r '.build_from.amd64 // .build_from // empty' "$build_file" 2>/dev/null)
      current_version=$(jq -r '.version // empty' "$build_file" 2>/dev/null)
    fi
  fi

  if [[ -z "$image" || "$image" == "null" ]]; then
    if [[ -f "$updater_file" ]]; then
      image=$(jq -r '.image // empty' "$updater_file" 2>/dev/null)
      current_version=$(jq -r '.version // empty' "$updater_file" 2>/dev/null)
    fi
  fi

  if [[ -z "$image" || "$image" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no valid Docker image defined, skipping."
    return
  fi

  local addon_slug=$(basename "$addon_path")

  log "$COLOR_PURPLE" "🧩 Addon: $addon_slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  local repo="${image%:*}"
  local tag="${image##*:}"

  # Skip 'latest' or any tag containing 'latest'
  if [[ "$tag" == "latest" || "$tag" == *"latest"* ]]; then
    log "$COLOR_YELLOW" "⚠️ Skipping add-on '$addon_slug' because Docker tag '$tag' is unsupported."
    return
  fi

  # Remove arch prefix (amd64-, arm64-, etc.) from tag for comparison
  local normalized_tag
  normalized_tag=$(echo "$tag" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

  # Compose Docker Hub API URL for tags
  local api_repo="$repo"
  # Convert lscr.io/linuxserver/... to linuxserver/...
  if [[ "$api_repo" =~ ^lscr.io/linuxserver/ ]]; then
    api_repo="${api_repo/lscr.io\/linuxserver\//linuxserver/}"
  fi
  # Remove docker.io prefix if exists
  api_repo="${api_repo#docker.io/}"

  local api_url="https://hub.docker.com/v2/repositories/${api_repo}/tags?page_size=100"

  local tags_json
  if ! tags_json=$(curl -s "$api_url"); then
    log "$COLOR_RED" "❌ Failed to fetch tags from Docker Hub API for $addon_slug"
    return
  fi

  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v 'latest' | grep -v 'rc' | sort -Vr | head -n1)

  if [[ -z "$latest_tag" ]]; then
    log "$COLOR_RED" "❌ Could not determine latest tag for $addon_slug"
    return
  fi

  log "$COLOR_GREEN" "🚀 Latest version: $latest_tag"
  log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

  # Check if update is needed
  if [[ "$normalized_tag" != "$latest_tag" ]]; then
    log "$COLOR_YELLOW" "⬆️  Updating $addon_slug from $tag to $latest_tag"

    # Update config.json version
    if [[ -f "$config_file" ]]; then
      jq --arg ver "$latest_tag" '.version = $ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
    fi

    # Update build.json version if exists
    if [[ -f "$build_file" ]]; then
      jq --arg ver "$latest_tag" '.version = $ver' "$build_file" > "$build_file.tmp" && mv "$build_file.tmp" "$build_file"
    fi

    # Update updater.json
    local now
    now=$(date '+%d-%m-%Y %H:%M')
    if [[ -f "$updater_file" ]]; then
      jq --arg ver "$latest_tag" --arg dt "$now" '.version = $ver | .last_update = $dt' "$updater_file" > "$updater_file.tmp" || \
      jq -n --arg slug "$addon_slug" --arg image "$image" --arg ver "$latest_tag" --arg dt "$now" '{slug: $slug, image: $image, version: $ver, last_update: $dt}' > "$updater_file.tmp"
      mv "$updater_file.tmp" "$updater_file"
    else
      jq -n --arg slug "$addon_slug" --arg image "$image" --arg ver "$latest_tag" --arg dt "$now" '{slug: $slug, image: $image, version: $ver, last_update: $dt}' > "$updater_file"
    fi

    # Create or append CHANGELOG.md
    if [[ ! -f "$changelog_file" ]]; then
      echo "# CHANGELOG for $addon_slug" > "$changelog_file"
    fi
    echo -e "\n## $latest_tag - $now\n- Updated Docker tag from \`$tag\` to \`$latest_tag\`" >> "$changelog_file"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $addon_slug"

    UPDATE_SUMMARY+="\n🔧 $addon_slug updated: $tag → $latest_tag"
    UPDATED=1
  else
    log "$COLOR_GREEN" "✔️ $addon_slug is already up to date ($tag)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  for addon_path in "$REPO_DIR"/*/; do
    # Only process folders with at least one config/build/updater file
    if [[ -f "$addon_path/config.json" || -f "$addon_path/build.json" || -f "$addon_path/updater.json" ]]; then
      update_addon_if_needed "$addon_path"
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config/build/updater JSON found"
    fi
  done

  if [[ $(git status --porcelain) ]]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed."
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi

  if [[ $UPDATED -eq 1 ]]; then
    send_notification "📦 Add-ons updated:$UPDATE_SUMMARY"
  fi
}

log "$COLOR_PURPLE" "🚀 Add-on Updater initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."

perform_update_check

log "$COLOR_GREEN" "⏳ Waiting for cron to trigger..."

# Simple cron simulation with sleep 60 in loop
while sleep 60; do :; done
