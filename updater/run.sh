#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Colors for output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"; shift
  echo -e "$(date -u '+[%Y-%m-%d %H:%M:%S UTC]') ${color}$*${COLOR_RESET}"
  echo "$(date -u '+[%Y-%m-%d %H:%M:%S UTC]') $*" >> "$LOG_FILE"
}

# Read timezone and cron schedule from config.json options
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
CRON_SCHEDULE=$(jq -r '.cron_schedule // "0 3 * * *"' "$CONFIG_PATH")

# Notification config
NOTIFY_GOTIFY_URL=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
NOTIFY_GOTIFY_TOKEN=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
NOTIFY_MAILRISE_URL=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
NOTIFY_APPRISE_URL=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")

# Function to send notifications (only if message is non-empty)
send_notification() {
  local message="$1"
  if [[ -z "$message" ]]; then
    return
  fi

  if [[ -n "$NOTIFY_GOTIFY_URL" && -n "$NOTIFY_GOTIFY_TOKEN" ]]; then
    curl -s -X POST "$NOTIFY_GOTIFY_URL/message?token=$NOTIFY_GOTIFY_TOKEN" -d "title=Addon Updater&message=$message" >/dev/null || true
  fi
  if [[ -n "$NOTIFY_MAILRISE_URL" ]]; then
    curl -s -X POST "$NOTIFY_MAILRISE_URL" -d "{\"message\":\"$message\"}" -H "Content-Type: application/json" >/dev/null || true
  fi
  if [[ -n "$NOTIFY_APPRISE_URL" ]]; then
    curl -s -X POST "$NOTIFY_APPRISE_URL" -d "body=$message" >/dev/null || true
  fi
}

# Function to get latest docker tag from Docker Hub
get_latest_dockerhub_tag() {
  local image="$1" # e.g. library/redis or technitium/dns-server
  # Docker Hub API expects repo without tag, e.g. technitium/dns-server
  local repo="${image%%:*}"

  # Extract namespace and repo for official repos (library/redis)
  # The API URL:
  # https://registry.hub.docker.com/v2/repositories/library/redis/tags?page_size=100
  # We'll fetch and parse tags JSON, get latest semver-ish tag
  local url="https://registry.hub.docker.com/v2/repositories/${repo}/tags?page_size=100"

  # Fetch tags list JSON
  local tags_json
  tags_json=$(curl -s "$url")

  # Parse tags, filter out 'latest', sort semver descending, pick top one
  # Fallback to 'latest' if no semver tag found
  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v 'latest' | sort -rV | head -n1)

  if [[ -z "$latest_tag" ]]; then
    latest_tag="latest"
  fi

  echo "$latest_tag"
}

# Function to get latest tag from LinuxServer.io docker image
get_latest_linuxserver_tag() {
  local image="$1" # e.g. lscr.io/linuxserver/heimdall
  # Use GitHub releases API for linuxserver images (mostly github.com/linuxserver/docker-<addon>)
  # Fallback to latest tag

  # Extract repo name after last slash:
  local repo_name="${image##*/}" # e.g. heimdall
  local github_repo="linuxserver/docker-${repo_name}"

  local release_json
  release_json=$(curl -s "https://api.github.com/repos/${github_repo}/releases/latest" || echo "{}")

  local latest_tag
  latest_tag=$(echo "$release_json" | jq -r '.tag_name // empty')

  if [[ -z "$latest_tag" ]]; then
    latest_tag="latest"
  fi

  echo "$latest_tag"
}

# Function to get latest GitHub container tag (assumes GHCR)
get_latest_github_tag() {
  local image="$1" # e.g. ghcr.io/username/repo
  # Extract repo path: remove ghcr.io/
  local repo_path="${image#ghcr.io/}"

  # API to list tags (GHCR doesn't have public API, fallback to latest)
  echo "latest"
}

# Update changelog file with new version and date
update_changelog() {
  local addon_dir="$1"
  local new_version="$2"
  local changelog_url="$3"

  local changelog_file="${addon_dir}/CHANGELOG.md"
  local date_str
  date_str=$(date -u +'%d-%m-%Y')

  if [[ ! -f "$changelog_file" ]]; then
    echo "## Changelog for $addon_dir" > "$changelog_file"
  fi

  echo -e "\nv$new_version ($date_str)\n\nUpdate to latest version (changelog: $changelog_url)" >> "$changelog_file"
  log "$COLOR_GREEN" "🆕 Created or updated CHANGELOG.md for $(basename "$addon_dir")"
}

# Main script start
log "$COLOR_PURPLE" "🔮 Add-on Updater started"
log "$COLOR_BLUE" "📅 Cron schedule: $CRON_SCHEDULE (Timezone: $TIMEZONE)"

# Calculate next run time in hours and minutes from cron schedule
next_run_sec=$(date -u --date="TZ=\"$TIMEZONE\" $(echo "$CRON_SCHEDULE" | awk '{print $2":"$1}')" +%s 2>/dev/null || echo 0)
now_sec=$(date -u +%s)
diff_sec=$((next_run_sec - now_sec))
if (( diff_sec < 0 )); then
  diff_sec=$((diff_sec + 86400)) # add one day if negative
fi
hours=$((diff_sec / 3600))
minutes=$(((diff_sec % 3600) / 60))
log "$COLOR_BLUE" "⏳ Next run in: $hours hours $minutes minutes"

log "$COLOR_BLUE" "🏃 Running update check..."

cd "$REPO_DIR"

# Pull latest changes from GitHub
if git pull --quiet origin main; then
  log "$COLOR_GREEN" "✅ Git pull successful."
else
  log "$COLOR_RED" "❌ Git pull failed!"
  exit 1
fi

UPDATED=false
NOTIFY_MSG=""

# Iterate each addon directory (assumed to be all directories with config.json)
for addon_dir in "$REPO_DIR"/*; do
  if [[ ! -d "$addon_dir" ]]; then
    continue
  fi
  config_file="$addon_dir/config.json"
  updater_file="$addon_dir/updater.json"
  build_file="$addon_dir/build.json"

  if [[ ! -f "$config_file" ]]; then
    log "$COLOR_YELLOW" "⚠️ Skipping $addon_dir, no config.json found."
    continue
  fi

  # Read slug, current version, image, url
  slug=$(jq -r '.slug // empty' "$config_file")
  current_version=$(jq -r '.version // empty' "$config_file")
  image=$(jq -r '.image // empty' "$config_file")
  url=$(jq -r '.url // empty' "$config_file")

  if [[ -z "$slug" ]]; then
    log "$COLOR_YELLOW" "⚠️ Addon at $addon_dir has no slug, skipping."
    continue
  fi
  if [[ -z "$image" || "$image" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Addon $slug missing image field, skipping."
    continue
  fi

  # Determine Docker image string (some are JSON maps)
  # If image is JSON object (multiple archs), pick amd64 or first key
  if jq -e . >/dev/null 2>&1 <<<"$image"; then
    # parse JSON object keys, pick amd64 or first key
    image_tag=""
    if echo "$image" | jq -e 'has("amd64")' >/dev/null; then
      image_tag=$(echo "$image" | jq -r '.amd64')
    else
      # pick first key's value
      image_tag=$(echo "$image" | jq -r 'to_entries[0].value')
    fi
  else
    image_tag="$image"
  fi

  # Strip possible tag from image_tag, e.g. "repo:tag" -> repo only
  repo_name="${image_tag%%:*}"

  # Fetch latest tag based on repo prefix
  latest_tag=""
  if [[ "$repo_name" =~ ^ghcr\.io/ ]]; then
    latest_tag=$(get_latest_github_tag "$repo_name")
  elif [[ "$repo_name" =~ ^lscr\.io/linuxserver/ ]]; then
    latest_tag=$(get_latest_linuxserver_tag "$repo_name")
  else
    latest_tag=$(get_latest_dockerhub_tag "$repo_name")
  fi

  if [[ -z "$latest_tag" ]]; then
    latest_tag="latest"
  fi

  # Current version can sometimes be full image string, clean it to only tag if possible
  # e.g. "repo:tag" => "tag"
  current_tag="${current_version##*:}"
  if [[ "$current_tag" == "$current_version" ]]; then
    current_tag="$current_version"
  fi

  log "$COLOR_PURPLE" "🧩 Addon: $slug"
  log "$COLOR_YELLOW" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image_tag"
  log "$COLOR_BLUE" "🚀 Latest version: $latest_tag"

  # Compare and update if needed
  if [[ "$current_tag" != "$latest_tag" ]]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_tag"

    # Update config.json version field
    tmp_config=$(mktemp)
    jq --arg ver "$latest_tag" '.version = $ver' "$config_file" > "$tmp_config" && mv "$tmp_config" "$config_file"

    # Update updater.json if exists
    if [[ -f "$updater_file" ]]; then
      dt_now=$(date -u '+%d-%m-%Y %H:%M')
      # Compose new image field for updater.json preserving original structure if JSON
      if jq -e . >/dev/null 2>&1 < "$updater_file"; then
        # Try to update "image" field intelligently (if JSON string map)
        if jq -e '.image | type == "object"' "$updater_file" >/dev/null; then
          tmp_updater=$(mktemp)
          jq --arg v "$latest_tag" --arg dt "$dt_now" --arg slug "$slug" \
            '.upstream_version=$v | .last_update=$dt | .slug=$slug | .image |= with_entries( .value |= sub(":.*$"; ":" + $v ))' \
            "$updater_file" > "$tmp_updater" && mv "$tmp_updater" "$updater_file"
        else
          tmp_updater=$(mktemp)
          jq --arg v "$latest_tag" --arg dt "$dt_now" --arg slug "$slug" \
            '.upstream_version=$v | .last_update=$dt | .slug=$slug | .image = $v' \
            "$updater_file" > "$tmp_updater" && mv "$tmp_updater" "$updater_file"
        fi
      else
        # updater.json invalid JSON, overwrite with minimal
        echo "{\"slug\":\"$slug\",\"upstream_version\":\"$latest_tag\",\"last_update\":\"$(date -u '+%d-%m-%Y %H:%M')\",\"image\":\"$latest_tag\"}" > "$updater_file"
      fi
      log "$COLOR_GREEN" "✅ Updated updater.json for $slug"
    fi

    # Update or create CHANGELOG.md with a link to Docker Hub tags page or GitHub releases URL if known
    changelog_url=""
    if [[ "$repo_name" =~ ^lscr\.io/linuxserver/ ]]; then
      # LinuxServer.io repos are mostly on github.com/linuxserver/docker-<name>
      addon_name="${repo_name##*/}"
      changelog_url="https://github.com/linuxserver/docker-${addon_name}/releases"
    elif [[ "$repo_name" =~ ^ghcr\.io/ ]]; then
      # GitHub Container Registry - fallback to GitHub releases
      repo_path="${repo_name#ghcr.io/}"
      changelog_url="https://github.com/${repo_path}/releases"
    else
      changelog_url="https://hub.docker.com/r/${repo_name}/tags"
    fi

    update_changelog "$addon_dir" "$latest_tag" "$changelog_url"

    UPDATED=true
    NOTIFY_MSG+="$slug: $current_version → $latest_tag\n"
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
done

if $UPDATED; then
  # Commit and push changes back to GitHub
  git config user.email "updater@local"
  git config user.name "Addon Updater Bot"

  git add .
  git commit -m "chore: update addon versions and changelogs [skip ci]" || true
  git push origin main || log "$COLOR_RED" "❌ Git push failed!"

  # Send notification
  send_notification "Add-ons updated:\n$NOTIFY_MSG"
else
  log "$COLOR_BLUE" "ℹ️ No changes to commit."
fi

log "$COLOR_PURPLE" "😴 Add-on Updater finished."

exit 0
