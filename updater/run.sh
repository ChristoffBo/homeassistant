#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Colors
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

# Read config
CRON_SCHEDULE=$(jq -r '.cron_schedule // "0 3 * * *"' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "Africa/Johannesburg"' "$CONFIG_PATH")
NOTIFY_GOTIFY=$(jq -r '.notify.gotify.enabled // false' "$CONFIG_PATH")
NOTIFY_MAILRISE=$(jq -r '.notify.mailrise.enabled // false' "$CONFIG_PATH")
NOTIFY_APPRISE=$(jq -r '.notify.apprise.enabled // false' "$CONFIG_PATH")
APPRISE_URL=$(jq -r '.notify.apprise.url // ""' "$CONFIG_PATH")

export TZ="$TIMEZONE"

log() {
  local color="$1"
  shift
  local timestamp
  timestamp=$(date +"%Y-%m-%d %H:%M:%S %Z")
  echo -e "[$timestamp] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Calculate time until next cron run (only supports daily cron at specific hour/min)
calc_time_to_next_run() {
  local cron_expr="$1"
  local minute hour
  minute=$(echo "$cron_expr" | awk '{print $1}')
  hour=$(echo "$cron_expr" | awk '{print $2}')

  local now_epoch next_epoch
  now_epoch=$(date +%s)

  next_epoch=$(date -d "$(date +%Y-%m-%d) $hour:$minute:00" +%s)

  if (( next_epoch <= now_epoch )); then
    next_epoch=$((next_epoch + 86400))
  fi

  local diff=$((next_epoch - now_epoch))
  local hours=$((diff / 3600))
  local minutes=$(((diff % 3600) / 60))

  if (( hours > 0 )); then
    echo "$hours hours $minutes minutes"
  else
    echo "$minutes minutes"
  fi
}

send_notifications() {
  local addon="$1"
  local old_version="$2"
  local new_version="$3"
  local message="Addon *${addon}* updated from \`${old_version}\` to \`${new_version}\`."

  if [ "$NOTIFY_GOTIFY" = "true" ]; then
    # Replace GOTIFY_URL and GOTIFY_TOKEN as needed or add in config.json
    local GOTIFY_URL=$(jq -r '.notify.gotify.url // ""' "$CONFIG_PATH")
    local GOTIFY_TOKEN=$(jq -r '.notify.gotify.token // ""' "$CONFIG_PATH")
    if [[ -n "$GOTIFY_URL" && -n "$GOTIFY_TOKEN" ]]; then
      curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
        -F "title=Addon Update: $addon" -F "message=$message" -F "priority=5" > /dev/null
    fi
  fi

  if [ "$NOTIFY_MAILRISE" = "true" ]; then
    # Mailrise URL in config.json notify.mailrise.url
    local MAILRISE_URL=$(jq -r '.notify.mailrise.url // ""' "$CONFIG_PATH")
    if [[ -n "$MAILRISE_URL" ]]; then
      curl -s -X POST "$MAILRISE_URL" -H "Content-Type: application/json" \
        -d "{\"message\":\"$message\"}" > /dev/null
    fi
  fi

  if [ "$NOTIFY_APPRISE" = "true" ]; then
    if [[ -n "$APPRISE_URL" ]]; then
      curl -s -X POST "$APPRISE_URL" -H "Content-Type: application/json" \
        -d "{\"title\":\"Addon Update: $addon\",\"body\":\"$message\"}" > /dev/null
    fi
  fi
}

update_changelog() {
  local addon_dir="$1"
  local new_version="$2"
  local changelog_url="$3"

  local changelog_file="$addon_dir/CHANGELOG.md"
  local date_str
  date_str=$(date +"%d-%m-%Y")

  if [ ! -f "$changelog_file" ]; then
    echo "Changelog for $addon_dir" > "$changelog_file"
  fi

  echo -e "\nv$new_version ($date_str)\n\nUpdate from upstream: $changelog_url\n" >> "$changelog_file"
}

update_updater_json() {
  local addon_dir="$1"
  local slug="$2"
  local version="$3"
  local image_json="$4"

  local updater_file="$addon_dir/updater.json"
  local date_str
  date_str=$(date +"%d-%m-%Y %H:%M")

  if [ -f "$updater_file" ]; then
    # Update fields with jq, fallback gracefully
    jq --arg v "$version" --arg dt "$date_str" --argjson img "$image_json" --arg slug "$slug" \
      '.upstream_version=$v | .last_update=$dt | .image=$img | .slug=$slug' "$updater_file" > "$updater_file.tmp" \
      && mv "$updater_file.tmp" "$updater_file"
  else
    # create if missing
    echo "{\"slug\":\"$slug\",\"upstream_version\":\"$version\",\"last_update\":\"$date_str\",\"image\":$image_json}" > "$updater_file"
  fi
}

fetch_latest_dockerhub_tag() {
  local image_name="$1"
  # Remove tag if any
  local image_base="${image_name%%:*}"
  # Fetch tags json, exclude non-semver (you can customize)
  local tags_json
  tags_json=$(curl -s "https://registry.hub.docker.com/v2/repositories/${image_base}/tags?page_size=50")

  # Extract latest stable tag (ignore 'latest' fallback)
  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v latest | head -n 1)

  if [ -z "$latest_tag" ]; then
    latest_tag="latest"
  fi

  echo "$latest_tag"
}

fetch_latest_github_release() {
  local repo="$1" # e.g. owner/repo
  local api_url="https://api.github.com/repos/${repo}/releases/latest"

  local tag
  tag=$(curl -s "$api_url" | jq -r '.tag_name')

  if [ "$tag" = "null" ] || [ -z "$tag" ]; then
    echo "latest"
  else
    echo "$tag"
  fi
}

fetch_latest_linuxserver_tag() {
  local image_name="$1" # e.g. linuxserver/heimdall
  # use Docker Hub api as linuxserver uses Docker Hub tags same
  fetch_latest_dockerhub_tag "$image_name"
}

update_addon() {
  local addon_dir="$1"
  local config_json="$addon_dir/config.json"

  if [ ! -f "$config_json" ]; then
    log "$COLOR_YELLOW" "⚠️ Addon directory $addon_dir missing config.json, skipping."
    return
  fi

  local slug version description image startup url changelog_url
  slug=$(jq -r '.slug' "$config_json")
  version=$(jq -r '.version' "$config_json")
  description=$(jq -r '.description' "$config_json")
  image=$(jq -r '.image // empty' "$config_json")
  startup=$(jq -r '.startup // empty' "$config_json")
  url=$(jq -r '.url // empty' "$config_json")
  changelog_url=$(jq -r '.changelog_url // empty' "$config_json")

  if [ -z "$image" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' missing image field, skipping."
    return
  fi

  # Determine image source and fetch latest tag
  local latest_tag=""
  if [[ "$image" == *"docker.io"* ]] || [[ "$image" =~ ^[a-z0-9./-]+(:[a-zA-Z0-9._-]+)?$ ]]; then
    # Docker Hub image
    local image_name=${image%%:*}
    latest_tag=$(fetch_latest_dockerhub_tag "$image_name")
  elif [[ "$image" == *"github.com"* ]]; then
    # Extract owner/repo from image string (assuming format: github.com/owner/repo or similar)
    local repo=$(echo "$image" | sed -E 's#.*/([^/]+/[^/:]+).*#\1#')
    latest_tag=$(fetch_latest_github_release "$repo")
  elif [[ "$image" == lscr.io* ]] || [[ "$image" == linuxserver/* ]]; then
    latest_tag=$(fetch_latest_linuxserver_tag "$image")
  else
    latest_tag="latest"
  fi

  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $version"
  log "$COLOR_BLUE" "📦 Image: $image"
  log "$COLOR_BLUE" "🔍 Checking latest tag for image $image"
  log "$COLOR_BLUE" "🚀 Latest version: $latest_tag"

  if [ "$version" != "$latest_tag" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $version to $latest_tag"

    # Update config.json version
    jq --arg v "$latest_tag" '.version=$v' "$config_json" > "$config_json.tmp" && mv "$config_json.tmp" "$config_json"

    # Update updater.json
    local image_json
    image_json=$(jq -n --arg aarch64 "${image%%:*}:$latest_tag" --arg amd64 "${image%%:*}:$latest_tag" '{aarch64:$aarch64,amd64:$amd64}')
    update_updater_json "$addon_dir" "$slug" "$latest_tag" "$image_json"

    # Update changelog
    if [ -n "$changelog_url" ]; then
      update_changelog "$addon_dir" "$latest_tag" "$changelog_url"
    fi

    # Notify only on update
    send_notifications "$slug" "$version" "$latest_tag"

  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

main() {
  log "$COLOR_PURPLE" "🔮 Add-on Updater started"
  log "$COLOR_PURPLE" "📅 Cron schedule: $CRON_SCHEDULE (Timezone: $TIMEZONE)"

  local time_to_next
  time_to_next=$(calc_time_to_next_run "$CRON_SCHEDULE")
  log "$COLOR_PURPLE" "⏳ Next run in: $time_to_next"

  log "$COLOR_PURPLE" "🏃 Running initial update check..."

  cd "$REPO_DIR"
  git pull origin main

  for addon_dir in addons/*; do
    if [ -d "$addon_dir" ]; then
      update_addon "$addon_dir"
    fi
  done

  # Commit and push changes if any
  if [ -n "$(git status --porcelain)" ]; then
    git add .
    git commit -m "Updated addon versions and changelogs [skip ci]"
    git push origin main
    log "$COLOR_GREEN" "✅ Changes committed and pushed."
  else
    log "$COLOR_GREEN" "ℹ️ No changes to commit."
  fi

  # Sleep until next cron run (calculated in seconds)
  local now_epoch next_epoch diff hour_sleep min_sleep sec_sleep
  now_epoch=$(date +%s)
  local minute hour
  minute=$(echo "$CRON_SCHEDULE" | awk '{print $1}')
  hour=$(echo "$CRON_SCHEDULE" | awk '{print $2}')
  next_epoch=$(date -d "$(date +%Y-%m-%d) $hour:$minute:00" +%s)
  if (( next_epoch <= now_epoch )); then
    next_epoch=$((next_epoch + 86400))
  fi
  diff=$((next_epoch - now_epoch))
  log "$COLOR_PURPLE" "😴 Sleeping for $diff seconds until next run..."
  sleep "$diff"
}

while true; do
  main
done
