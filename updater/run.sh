#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ="$TIMEZONE"

# Load notifier config
NOTIFIER_ENABLED=$(jq -r '.notifier.enabled // false' "$CONFIG_PATH")
NOTIFIER_TYPE=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
NOTIFIER_URL=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
NOTIFIER_TOKEN=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron // "0 * * * *"' "$CONFIG_PATH")  # default hourly

# Colors for logs
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
  if [[ "$NOTIFIER_ENABLED" != "true" ]]; then
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
  log "$COLOR_PURPLE" "🔔 Notification sent"
}

# Get latest tag from Docker Hub, ignoring 'rc' and sorting versions descending
get_latest_docker_tag() {
  local repo="$1"
  local api_repo="${repo#lscr.io/}"
  api_repo="${api_repo#docker.io/}"

  local tags_json
  tags_json=$(curl -s "https://hub.docker.com/v2/repositories/$api_repo/tags?page_size=100" || echo "{}")
  local tags
  tags=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null || echo "")

  # Filter out release candidates, sort descending, ignore empty lines
  local filtered_tags
  filtered_tags=$(echo "$tags" | grep -v -E 'rc' | grep -v '^$' || true)

  # Pick latest versioned tag ignoring 'latest'
  local latest_version_tag
  latest_version_tag=$(echo "$filtered_tags" | grep -v '^latest$' | sort -Vr | head -n1)

  # Return latest_version_tag or empty if none found
  echo "$latest_version_tag"
}

UPDATE_SUMMARY=""
UPDATED=0

update_addon_if_needed() {
  local addon_dir="$1"

  # Determine files for version and image info, priority: config.json, build.json, updater.json
  local config_file="$addon_dir/config.json"
  local build_file="$addon_dir/build.json"
  local updater_file="$addon_dir/updater.json"
  local changelog_file="$addon_dir/CHANGELOG.md"

  # Skip if no config or build file
  if [[ ! -f "$config_file" && ! -f "$build_file" && ! -f "$updater_file" ]]; then
    log "$COLOR_YELLOW" "⚠️ Skipping add-on '$(basename "$addon_dir")' - no config/build/updater JSON found"
    return
  fi

  # Extract image and current version from config, else build, else updater
  local image current_version slug
  slug=$(basename "$addon_dir")

  if [[ -f "$config_file" ]]; then
    image=$(jq -r '.image // empty' "$config_file")
    current_version=$(jq -r '.version // empty' "$config_file")
    slug=$(jq -r '.slug // empty' "$config_file")
    [[ -z "$slug" || "$slug" == "null" ]] && slug=$(basename "$addon_dir")
  fi

  if [[ -z "$image" || "$image" == "null" ]]; then
    if [[ -f "$build_file" ]]; then
      # Get architecture, fallback to amd64
      local arch=$(uname -m)
      [[ "$arch" == "x86_64" ]] && arch="amd64"
      image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
    fi
  fi

  if [[ -z "$current_version" || "$current_version" == "null" ]]; then
    if [[ -f "$build_file" ]]; then
      current_version=$(jq -r '.version // empty' "$build_file")
    elif [[ -f "$updater_file" ]]; then
      current_version=$(jq -r '.version // empty' "$updater_file")
    fi
  fi

  # If no image, skip
  if [[ -z "$image" || "$image" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' has no Docker image defined, skipping."
    return
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_PURPLE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  # Parse repo and tag
  if [[ "$image" == *":"* ]]; then
    repo="${image%:*}"
    tag="${image##*:}"
  else
    repo="$image"
    tag="latest"
  fi

  # Normalize current version and tag by removing arch prefixes
  norm_current_version=$(echo "$current_version" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')
  norm_tag=$(echo "$tag" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

  # Get latest docker tag
  latest_version_tag=$(get_latest_docker_tag "$repo")

  # Decide chosen tag
  chosen_tag=""

  if [[ "$norm_current_version" == "latest" || -z "$norm_current_version" ]]; then
    if [[ -n "$latest_version_tag" ]]; then
      chosen_tag="$latest_version_tag"
    else
      chosen_tag="latest"
    fi
  else
    if [[ -n "$latest_version_tag" ]]; then
      chosen_tag="$latest_version_tag"
    else
      chosen_tag="$norm_current_version"
    fi
  fi

  log "$COLOR_GREEN" "🚀 Latest version candidate: $chosen_tag"
  log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

  # If the chosen tag is 'latest' but current is not, or different version found, update
  if [[ "$norm_current_version" != "$chosen_tag" ]]; then
    # If chosen tag is 'latest' and current is also 'latest', do nothing (already up to date)
    if [[ "$chosen_tag" == "latest" && "$norm_current_version" == "latest" ]]; then
      log "$COLOR_GREEN" "✔️ $slug is already up to date (latest)"
    else
      log "$COLOR_YELLOW" "⬆️  Updating $slug from $current_version to $chosen_tag"

      # Update config.json version
      if [[ -f "$config_file" ]]; then
        jq --arg ver "$chosen_tag" '.version = $ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
      fi

      # Update build.json version if exists
      if [[ -f "$build_file" ]]; then
        jq --arg ver "$chosen_tag" '.version = $ver' "$build_file" > "$build_file.tmp" && mv "$build_file.tmp" "$build_file"
      fi

      # Update updater.json version and last_update timestamp
      local dt
      dt=$(date '+%d-%m-%Y %H:%M')
      if [[ -f "$updater_file" ]]; then
        jq --arg ver "$chosen_tag" --arg d "$dt" '.version = $ver | .last_update = $d' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"
      else
        jq -n --arg slug "$slug" --arg ver "$chosen_tag" --arg d "$dt" '{slug: $slug, version: $ver, last_update: $d}' > "$updater_file"
      fi

      # Create or append to CHANGELOG.md
      if [[ ! -f "$changelog_file" ]]; then
        echo "# Changelog for $slug" > "$changelog_file"
        echo "" >> "$changelog_file"
      fi
      echo -e "\n## $chosen_tag - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$tag\` to \`$chosen_tag\`" >> "$changelog_file"
      log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

      UPDATED=1
      UPDATE_SUMMARY+="\n🔧 $slug updated from $current_version → $chosen_tag"
    fi
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

# Run update check on all add-ons
log "$COLOR_PURPLE" "🔮 Starting add-on update check..."
cd "$REPO_DIR" || exit 1

for addon_dir in */ ; do
  update_addon_if_needed "$REPO_DIR/$addon_dir"
done

# Commit and push if updates found
if [[ $UPDATED -eq 1 ]]; then
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"
  git add .
  if git commit -m "⬆️ Update add-on versions" >> "$LOG_FILE" 2>&1; then
    git push origin main >> "$LOG_FILE" 2>&1 || log "$COLOR_RED" "❌ Git push failed"
  else
    log "$COLOR_YELLOW" "⚠️ Nothing to commit"
  fi
  send_notification "📦 Home Assistant add-ons updated:$UPDATE_SUMMARY"
else
  log "$COLOR_GREEN" "✅ No updates detected, nothing to commit."
fi

# Schedule next run with cron if cron is installed
if command -v cron >/dev/null 2>&1; then
  log "$COLOR_BLUE" "⏳ Scheduling cron with: $CHECK_CRON"
  # Write crontab line (run this script every schedule)
  (crontab -l 2>/dev/null | grep -v 'run.sh'; echo "$CHECK_CRON bash /data/run.sh") | crontab -
  # Start cron daemon
  cron -f
else
  log "$COLOR_YELLOW" "⚠️ Cron not found, script will exit after this run."
fi

# Keep script alive if cron is running
while true; do sleep 60; done
