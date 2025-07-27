#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config and export for date command
TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ

# Colored logging setup
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
    if git clone "$(jq -r '.github_repo' "$CONFIG_PATH")" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      exit 1
    fi
  else
    log "$COLOR_PURPLE" "🔄 Pulling latest changes from GitHub..."
    cd "$REPO_DIR"
    if git pull origin main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git pull successful."
    else
      log "$COLOR_RED" "❌ Git pull failed."
    fi
  fi
}

get_latest_docker_tag() {
  local image_repo="$1"

  # Normalize repo URL if needed (remove registry domain)
  local normalized_repo="$image_repo"
  normalized_repo="${normalized_repo#lscr.io/}"  # Remove lscr.io prefix if present
  normalized_repo="${normalized_repo#docker.io/}" # Remove docker.io prefix if present

  # Docker Hub API URL
  local api_url="https://hub.docker.com/v2/repositories/${normalized_repo}/tags?page_size=100"

  # Fetch tags, ignore any with 'latest' or 'rc' or empty tags
  local tags=$(curl -s "$api_url" | jq -r '.results[].name' 2>/dev/null || echo "")

  # Filter out any tags containing 'latest' or 'rc'
  local filtered_tags=$(echo "$tags" | grep -v -E 'latest|rc' || true)

  # Pick the latest version tag sorted naturally descending
  local latest_tag=$(echo "$filtered_tags" | sort -Vr | head -n1)

  echo "$latest_tag"
}

UPDATE_SUMMARY=""
UPDATED=0

perform_update_check() {
  clone_or_update_repo
  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  for addon_path in "$REPO_DIR"/*/; do
    # Check config.json, build.json, updater.json in that order for image and version
    local config_json="$addon_path/config.json"
    local build_json="$addon_path/build.json"
    local updater_json="$addon_path/updater.json"
    local changelog_md="$addon_path/CHANGELOG.md"

    local image=""
    local current_version=""

    if [ -f "$config_json" ]; then
      image=$(jq -r '.image // empty' "$config_json")
      current_version=$(jq -r '.version // empty' "$config_json")
    fi

    if [[ -z "$image" || "$image" == "null" ]] && [ -f "$build_json" ]; then
      image=$(jq -r '.build_from.amd64 // .build_from // empty' "$build_json")
      current_version=$(jq -r '.version // empty' "$build_json")
    fi

    if [[ -z "$image" || "$image" == "null" ]] && [ -f "$updater_json" ]; then
      image=$(jq -r '.image // empty' "$updater_json")
      current_version=$(jq -r '.version // empty' "$updater_json")
    fi

    # If still empty skip addon
    if [[ -z "$image" || "$image" == "null" ]]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
      continue
    fi

    # Extract image tag from image name (repo:tag)
    local repo="${image%%:*}"
    local tag="${image##*:}"

    # If current_version is empty, use image tag as current version
    if [[ -z "$current_version" || "$current_version" == "null" ]]; then
      current_version="$tag"
    fi

    log "$COLOR_PURPLE" "🧩 Addon: $(basename "$addon_path")"
    log "$COLOR_BLUE" "🔢 Current version: $current_version"
    log "$COLOR_BLUE" "📦 Image: $image"

    # Skip if current tag is 'latest' or contains 'latest'
    if [[ "$current_version" == "latest" || "$current_version" == *"latest"* ]]; then
      log "$COLOR_YELLOW" "⚠️ Skipping add-on '$(basename "$addon_path")' because Docker tag '$current_version' is unsupported."
      log "$COLOR_BLUE" "----------------------------"
      continue
    fi

    # Fetch latest tag from Docker Hub (skip latest tags)
    local latest_version
    latest_version=$(get_latest_docker_tag "$repo")

    if [[ -z "$latest_version" || "$latest_version" == "null" ]]; then
      log "$COLOR_RED" "❌ Could not fetch tags for $repo"
      log "$COLOR_BLUE" "----------------------------"
      continue
    fi

    log "$COLOR_BLUE" "🚀 Latest version: $latest_version"
    log "$COLOR_BLUE" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

    if [[ "$current_version" != "$latest_version" ]]; then
      log "$COLOR_GREEN" "⬆️  Updating $(basename "$addon_path") from $current_version to $latest_version"

      # Update config.json version if exists
      if [ -f "$config_json" ]; then
        jq --arg v "$latest_version" '.version = $v' "$config_json" > "$config_json.tmp" && mv "$config_json.tmp" "$config_json"
      fi

      # Update build.json version if exists
      if [ -f "$build_json" ]; then
        jq --arg v "$latest_version" '.version = $v' "$build_json" > "$build_json.tmp" && mv "$build_json.tmp" "$build_json"
      fi

      # Update updater.json (or create if missing)
      if [ -f "$updater_json" ]; then
        jq --arg v "$latest_version" --arg dt "$(date '+%d-%m-%Y %H:%M')" \
          '.version = $v | .last_update = $dt' "$updater_json" > "$updater_json.tmp" && mv "$updater_json.tmp" "$updater_json"
      else
        jq -n --arg slug "$(basename "$addon_path")" --arg image "$image" --arg v "$latest_version" --arg dt "$(date '+%d-%m-%Y %H:%M')" \
          '{slug: $slug, image: $image, version: $v, last_update: $dt}' > "$updater_json"
      fi

      # Create or append CHANGELOG.md
      if [ ! -f "$changelog_md" ]; then
        echo "# Changelog for $(basename "$addon_path")" > "$changelog_md"
        echo "" >> "$changelog_md"
      fi
      echo -e "## $latest_version - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$current_version\` to \`$latest_version\`" >> "$changelog_md"

      log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $(basename "$addon_path")"

      UPDATED=1
      UPDATE_SUMMARY+="\n🔧 $(basename "$addon_path") updated: $current_version → $latest_version"
    else
      log "$COLOR_GREEN" "✔️ $(basename "$addon_path") is already up to date ($current_version)"
    fi

    log "$COLOR_BLUE" "----------------------------"
  done

  # Commit and push if updates were made
  if [ $UPDATED -eq 1 ]; then
    git add .
    git commit -m "⬆️ Update add-on versions" >> "$LOG_FILE" 2>&1 || true
    if git push origin main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
      send_notification "📦 Home Assistant add-ons updated:$UPDATE_SUMMARY"
    else
      log "$COLOR_RED" "❌ Git push failed."
    fi
  else
    log "$COLOR_GREEN" "✅ No updates needed."
  fi
}

# Read cron schedule from config
CHECK_CRON=$(jq -r '.check_cron // "0 * * * *"' "$CONFIG_PATH")

log "$COLOR_PURPLE" "🚀 Add-on Updater initialized"
log "$COLOR_PURPLE" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TZ)"
log "$COLOR_PURPLE" "🏃 Running initial update check on startup..."

perform_update_check

log "$COLOR_PURPLE" "⏳ Waiting for cron trigger..."

# Run cron job loop
while sleep 60; do
  if date +'%M %H %d %m %w' | grep -q -F "$(echo "$CHECK_CRON" | awk '{print $2, $1, $3, $4, $5}')"; then
    perform_update_check
  fi
done
