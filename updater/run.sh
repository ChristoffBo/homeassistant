#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config (default to UTC)
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ="$TIMEZONE"

# Load GitHub credentials and repo
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")

# Notifier config
NOTIFIER_TYPE=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
NOTIFIER_URL=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
NOTIFIER_TOKEN=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")

# Cron schedule config (not directly used here, but logged)
CHECK_CRON=$(jq -r '.check_cron // empty' "$CONFIG_PATH")

# Colored logging
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

# Clear log file on startup
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "[\033[90m$(date '+%Y-%m-%d %H:%M:%S %Z')\033[0m] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

send_notification() {
  local message="$1"
  if [[ -z "$NOTIFIER_TYPE" || -z "$NOTIFIER_URL" ]]; then
    return
  fi
  case "$NOTIFIER_TYPE" in
    gotify)
      curl -s -X POST "$NOTIFIER_URL/message" \
        -H "X-Gotify-Key: $NOTIFIER_TOKEN" \
        -F "title=Addon Updater" \
        -F "message=$message" \
        -F "priority=5" > /dev/null || true
      ;;
    mailrise)
      curl -s -X POST "$NOTIFIER_URL" -H "Content-Type: text/plain" --data "$message" > /dev/null || true
      ;;
    apprise)
      curl -s "$NOTIFIER_URL" -d "$message" > /dev/null || true
      ;;
    *)
      log "$COLOR_RED" "❌ Unknown notifier type: $NOTIFIER_TYPE"
      ;;
  esac
  log "$COLOR_PURPLE" "🔔 Notification sent."
}

# Construct authenticated Git repo URL if credentials provided
if [[ -n "$GITHUB_USERNAME" && -n "$GITHUB_TOKEN" ]]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
else
  GIT_AUTH_REPO="$GITHUB_REPO"
fi

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

# Extract Docker tag from image string (default fallback)
extract_tag() {
  local image="$1"
  # If image contains ":", tag is the part after last colon
  if [[ "$image" == *:* ]]; then
    echo "${image##*:}"
  else
    echo "latest"
  fi
}

# Get Docker tags from Docker Hub API for a repo
get_docker_tags() {
  local repo="$1"
  # Replace registry prefix for API compatibility
  local repo_api="${repo#lscr.io/}"
  repo_api="${repo_api#docker.io/}"
  # Query Docker Hub API (limited to 100 tags)
  curl -s "https://hub.docker.com/v2/repositories/$repo_api/tags?page_size=100" | jq -r '.results[].name' || true
}

UPDATE_OCCURRED=0
UPDATE_SUMMARY=""

update_addon() {
  local addon_dir="$1"
  local config_json="$addon_dir/config.json"
  local build_json="$addon_dir/build.json"
  local updater_json="$addon_dir/updater.json"
  local changelog_md="$addon_dir/CHANGELOG.md"

  # Try to get image and version from config.json, then build.json, then updater.json
  local image=""
  local current_version=""
  if [[ -f "$config_json" ]]; then
    image=$(jq -r '.image // empty' "$config_json")
    current_version=$(jq -r '.version // empty' "$config_json")
  fi
  if [[ -z "$image" || "$image" == "null" ]]; then
    if [[ -f "$build_json" ]]; then
      image=$(jq -r '.build_from // empty' "$build_json")
      current_version=$(jq -r '.version // empty' "$build_json")
    fi
  fi
  if [[ -z "$image" || "$image" == "null" ]]; then
    if [[ -f "$updater_json" ]]; then
      image=$(jq -r '.image // empty' "$updater_json")
      current_version=$(jq -r '.version // empty' "$updater_json")
    fi
  fi

  if [[ -z "$image" || "$image" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_dir")' has no Docker image defined, skipping."
    return
  fi

  local slug=$(basename "$addon_dir")

  log "$COLOR_PURPLE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  local current_tag
  current_tag=$(extract_tag "$image")

  # If current tag is 'latest' or contains 'latest', allow fallback but warn
  if [[ "$current_tag" == "latest" || "$current_tag" == *latest* ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' uses unsupported 'latest' Docker tag; will try to find latest version tag."
  fi

  # Extract repo (remove tag)
  local repo="${image%:*}"

  # Fetch tags and pick latest semver-like tag ignoring 'latest' and 'rc' etc.
  local tags
  tags=$(get_docker_tags "$repo" | grep -v -iE 'latest|rc|beta|alpha' || true)
  if [[ -z "$tags" ]]; then
    log "$COLOR_RED" "❌ Could not fetch tags for $repo"
    return
  fi

  # Sort tags descending (simple version, could be improved)
  local latest_tag
  latest_tag=$(echo "$tags" | sort -Vr | head -n1)

  if [[ -z "$latest_tag" ]]; then
    log "$COLOR_RED" "❌ No suitable tags found for $repo"
    return
  fi

  log "$COLOR_GREEN" "🚀 Latest version: $latest_tag"
  log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

  # Compare normalized current tag with latest_tag
  # Remove arch prefix like amd64- etc.
  local normalized_current_tag
  normalized_current_tag=$(echo "$current_tag" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

  if [[ "$normalized_current_tag" != "$latest_tag" ]]; then
    log "$COLOR_YELLOW" "⬆️  Updating $slug from $current_tag to $latest_tag"

    # Update version in config.json if exists
    if [[ -f "$config_json" ]]; then
      jq --arg v "$latest_tag" '.version = $v' "$config_json" > "$config_json.tmp" && mv "$config_json.tmp" "$config_json"
    fi

    # Update version in build.json if exists
    if [[ -f "$build_json" ]]; then
      jq --arg v "$latest_tag" '.version = $v' "$build_json" > "$build_json.tmp" && mv "$build_json.tmp" "$build_json"
    fi

    # Update version in updater.json or create if missing
    local now_date
    now_date=$(date '+%d-%m-%Y %H:%M')
    if [[ -f "$updater_json" ]]; then
      jq --arg v "$latest_tag" --arg dt "$now_date" '.version = $v | .last_update = $dt' "$updater_json" > "$updater_json.tmp" && mv "$updater_json.tmp" "$updater_json"
    else
      jq -n --arg slug "$slug" --arg v "$latest_tag" --arg dt "$now_date" \
        '{slug: $slug, version: $v, last_update: $dt}' > "$updater_json"
    fi

    # Update or create CHANGELOG.md
    if [[ ! -f "$changelog_md" ]]; then
      echo "# CHANGELOG for $slug" > "$changelog_md"
    fi
    echo -e "\n## $latest_tag - $now_date\n- Updated Docker tag from \`$current_tag\` to \`$latest_tag\`" >> "$changelog_md"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    UPDATE_SUMMARY+="\n🔧 $slug updated from $current_tag → $latest_tag"
    UPDATE_OCCURRED=1
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_tag)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  for addon_dir in "$REPO_DIR"/*/; do
    if [[ -f "$addon_dir/config.json" || -f "$addon_dir/build.json" || -f "$addon_dir/updater.json" ]]; then
      update_addon "$addon_dir"
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_dir") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if ! git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_RED" "❌ Git push failed."
    else
      log "$COLOR_GREEN" "✅ Git push successful."
    fi
  else
    log "$COLOR_GREEN" "📦 No add-on updates found; no commit necessary."
  fi

  if [[ $UPDATE_OCCURRED -eq 1 ]]; then
    send_notification "📦 Add-ons updated:$UPDATE_SUMMARY"
  fi
}

log "$COLOR_PURPLE" "🔮 Add-on Updater started"
log "$COLOR_GREEN" "⏰ Scheduled cron: ${CHECK_CRON:-Not set} (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check..."
perform_update_check
log "$COLOR_GREEN" "⏳ Waiting for cron to trigger..."

# Keep script running (cron will trigger updates)
while sleep 60; do :; done
