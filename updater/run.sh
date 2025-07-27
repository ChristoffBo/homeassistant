#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ=$TIMEZONE

# Colors for logging
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
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Cloning repository..."
    git clone "$(jq -r '.github_repo' "$CONFIG_PATH")" "$REPO_DIR" >> "$LOG_FILE" 2>&1 && \
      log "$COLOR_GREEN" "✅ Repository cloned successfully." || \
      { log "$COLOR_RED" "❌ Failed to clone repository."; exit 1; }
  else
    log "$COLOR_PURPLE" "🔄 Pulling latest changes..."
    cd "$REPO_DIR"
    git pull >> "$LOG_FILE" 2>&1 && \
      log "$COLOR_GREEN" "✅ Git pull successful." || \
      log "$COLOR_RED" "❌ Git pull failed."
  fi
}

get_latest_docker_tag() {
  local repo="$1"
  # Extract repo name removing any registry prefix (like lscr.io/)
  local clean_repo="${repo#*/}"
  local api_url="https://hub.docker.com/v2/repositories/$clean_repo/tags?page_size=100"

  # Fetch tags JSON
  local tags_json
  tags_json=$(curl -s "$api_url" || echo "{}")

  # Extract tags excluding 'latest' and pre-release tags like 'rc'
  echo "$tags_json" | jq -r '.results[].name' | grep -v -E 'latest|rc|beta|alpha' | sort -Vr | head -n1
}

resolve_image_for_arch() {
  local image_json="$1"
  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64) arch="amd64" ;;
    armv7l) arch="armv7" ;;
    aarch64) arch="aarch64" ;;
  esac

  # Check if image_json is an object
  if jq -e 'type=="object"' <<<"$image_json" >/dev/null 2>&1; then
    # Try to get image for current arch, fallback to amd64, then armv7, then aarch64
    local image
    image=$(jq -r --arg arch "$arch" '.[$arch] // .amd64 // .armv7 // .aarch64 // empty' <<<"$image_json")
    echo "$image"
  else
    # It's a string, just return
    echo "$image_json" | tr -d '"'
  fi
}

update_addon_if_needed() {
  local addon_path="$1"

  local config_json="$addon_path/config.json"
  local build_json="$addon_path/build.json"
  local updater_json="$addon_path/updater.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  local slug
  slug=$(jq -r '.slug // empty' "$config_json" 2>/dev/null)
  if [[ -z "$slug" ]]; then slug=$(basename "$addon_path"); fi

  # Load image field from config.json, else build.json, else updater.json
  local image_raw=""
  if [[ -f "$config_json" ]]; then
    image_raw=$(jq -c '.image // empty' "$config_json")
  fi
  if [[ -z "$image_raw" || "$image_raw" == "null" ]]; then
    if [[ -f "$build_json" ]]; then
      image_raw=$(jq -c '.build_from // empty' "$build_json")
    fi
  fi
  if [[ -z "$image_raw" || "$image_raw" == "null" ]]; then
    if [[ -f "$updater_json" ]]; then
      image_raw=$(jq -c '.image // empty' "$updater_json")
    fi
  fi

  if [[ -z "$image_raw" || "$image_raw" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' has no Docker image defined, skipping."
    return
  fi

  local image
  image=$(resolve_image_for_arch "$image_raw")
  if [[ -z "$image" ]]; then
    log "$COLOR_RED" "❌ Could not resolve Docker image for add-on $slug"
    return
  fi

  # Extract tag from image
  local tag="${image##*:}"
  local repo="${image%:*}"

  # Handle 'latest' tag - allow checking for proper latest version instead of skipping outright
  if [[ "$tag" == "latest" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' uses 'latest' tag; will try to find latest specific version tag."
    tag=""
  fi

  # Get current version from config.json or updater.json
  local current_version
  current_version=$(jq -r '.version // empty' "$config_json" 2>/dev/null)
  if [[ -z "$current_version" || "$current_version" == "null" ]]; then
    if [[ -f "$updater_json" ]]; then
      current_version=$(jq -r '.version // empty' "$updater_json")
    fi
  fi
  current_version=${current_version:-""}

  # Determine latest tag from Docker Hub API
  local latest_tag
  latest_tag=$(get_latest_docker_tag "$repo")

  if [[ -z "$latest_tag" ]]; then
    if [[ -n "$tag" ]]; then
      latest_tag="$tag"
    else
      log "$COLOR_RED" "❌ Could not fetch tags for $repo"
      return
    fi
  fi

  log "$COLOR_PURPLE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: ${current_version:-"unknown"}"
  log "$COLOR_BLUE" "📦 Image: $image"
  log "$COLOR_BLUE" "🚀 Latest version: $latest_tag"

  if [[ "$current_version" != "$latest_tag" ]]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_tag"

    # Update config.json version
    jq --arg v "$latest_tag" '.version = $v' "$config_json" > "$config_json.tmp" && mv "$config_json.tmp" "$config_json"

    # Update updater.json version and last_update timestamp
    local now_ts
    now_ts=$(date '+%d-%m-%Y %H:%M')
    if [[ -f "$updater_json" ]]; then
      jq --arg v "$latest_tag" --arg dt "$now_ts" '.version = $v | .last_update = $dt' "$updater_json" > "$updater_json.tmp" && mv "$updater_json.tmp" "$updater_json"
    else
      echo "{\"version\":\"$latest_tag\",\"last_update\":\"$now_ts\"}" > "$updater_json"
    fi

    # Update CHANGELOG.md (create if missing)
    if [[ ! -f "$changelog_file" ]]; then
      echo "# CHANGELOG for $slug" > "$changelog_file"
      echo >> "$changelog_file"
    fi
    echo -e "\n## $latest_tag - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$current_version\` to \`$latest_tag\`" >> "$changelog_file"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    UPDATE_SUMMARY+="\n🔧 $slug updated from $current_version → $latest_tag"
    UPDATED=1
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

main() {
  UPDATED=0
  UPDATE_SUMMARY=""

  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  for addon_path in "$REPO_DIR"/*/; do
    if [[ -f "$addon_path/config.json" || -f "$addon_path/build.json" || -f "$addon_path/updater.json" ]]; then
      update_addon_if_needed "$addon_path"
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config/build/updater JSON found"
    fi
  done

  # Commit and push only if updated
  if [[ $UPDATED -eq 1 ]]; then
    git add .
    if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
      if git push >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "✅ Git push successful."
      else
        log "$COLOR_RED" "❌ Git push failed."
      fi
    else
      log "$COLOR_RED" "❌ Git commit failed."
    fi
    send_notification "📦 Home Assistant add-ons updated:$UPDATE_SUMMARY"
  else
    log "$COLOR_GREEN" "✅ No updates found."
  fi
}

# Read cron from config
CHECK_CRON=$(jq -r '.check_cron // empty' "$CONFIG_PATH")
if [[ -z "$CHECK_CRON" ]]; then
  log "$COLOR_YELLOW" "⚠️ Cron schedule not set in config, script will run once and exit."
  main
  exit 0
fi

log "$COLOR_PURPLE" "🚀 Add-on Updater started"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"

main &

# Wait for cron schedule to run repeatedly
while true; do
  sleep 60
  CURRENT_MINUTE=$(date +%M)
  CURRENT_HOUR=$(date +%H)

  # Simple cron parser: supports only minute and hour fields in format "m h * * *"
  CRON_MINUTE=$(echo "$CHECK_CRON" | awk '{print $1}')
  CRON_HOUR=$(echo "$CHECK_CRON" | awk '{print $2}')

  if [[ "$CRON_MINUTE" == "$CURRENT_MINUTE" && "$CRON_HOUR" == "$CURRENT_HOUR" ]]; then
    main
  fi
done
