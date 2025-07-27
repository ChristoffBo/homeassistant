#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

notify() {
  local message="$1"
  local title="${2:-Home Assistant Add-on Updater}"

  local gotify_url=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
  local gotify_token=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
  local mailrise_url=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
  local mailrise_token=$(jq -r '.mailrise.token // empty' "$CONFIG_PATH")
  local apprise_url=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")

  if [ -n "$gotify_url" ] && [ -n "$gotify_token" ]; then
    curl -s -X POST "$gotify_url/message?token=$gotify_token" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"message\":\"$message\",\"priority\":5}" > /dev/null 2>&1
  fi

  if [ -n "$mailrise_url" ] && [ -n "$mailrise_token" ]; then
    curl -s -X POST "$mailrise_url/api/notification" \
      -H "Authorization: Bearer $mailrise_token" \
      -H "Content-Type: application/json" \
      -d "{\"message\":\"$message\",\"title\":\"$title\"}" > /dev/null 2>&1
  fi

  if [ -n "$apprise_url" ]; then
    curl -s -X POST "$apprise_url" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"body\":\"$message\"}" > /dev/null 2>&1
  fi
}

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Cloning repository..."
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
      notify "Repository cloned successfully." "Add-on Updater"
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      notify "Failed to clone repository." "Add-on Updater ERROR"
      exit 1
    fi
  else
    log "$COLOR_PURPLE" "🔄 Pulling latest changes from GitHub..."
    cd "$REPO_DIR"
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git pull successful."
      notify "Git pull successful." "Add-on Updater"
    else
      log "$COLOR_RED" "❌ Git pull failed."
      notify "Git pull failed." "Add-on Updater ERROR"
    fi
  fi
}

# Fetch latest Docker tag from Docker Hub
fetch_latest_dockerhub_tag() {
  local image="$1"
  local repo tag

  repo="${image%:*}"    # Remove tag if present
  repo="${repo#*/}"     # Strip possible registry prefix (docker.io/...)

  # Query Docker Hub tags JSON and pick the latest non 'latest' tag
  tag=$(curl -s "https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100" | \
    jq -r '.results[].name' | grep -vE '^latest$' | sort -V | tail -n1)
  echo "${tag:-latest}"
}

# Fetch latest tag from GitHub Container Registry or gitun.io
fetch_latest_github_tag() {
  local image="$1"
  local repo tag
  # image like ghcr.io/org/repo or gitun.io/org/repo

  repo=$(echo "$image" | sed -E 's|^(ghcr\.io|gitun\.io)/([^/:]+/[^/:]+).*|\2|')

  # Here you could use GitHub API or gitun API to get latest tag
  # For now, fallback to "latest"
  echo "latest"
}

# Fetch latest tag from LinuxServer.io docker images
fetch_latest_linuxserver_tag() {
  local image="$1"
  # Example: linuxserver/heimdall
  # LinuxServer uses Docker Hub mostly so fallback to DockerHub
  fetch_latest_dockerhub_tag "$image"
}

get_latest_docker_tag() {
  local image="$1"
  if [[ "$image" =~ ^ghcr\.io/ ]] || [[ "$image" =~ ^gitun\.io/ ]]; then
    fetch_latest_github_tag "$image"
  elif [[ "$image" =~ ^linuxserver/ ]] || [[ "$image" =~ ^lscr\.io/linuxserver/ ]]; then
    fetch_latest_linuxserver_tag "$image"
  else
    fetch_latest_dockerhub_tag "$image"
  fi
}

fix_updater_json() {
  local updater_file="$1"
  local slug="$2"
  local image="$3"
  local version="$4"
  local timestamp="$5"

  if [ ! -f "$updater_file" ] || ! jq -e . "$updater_file" >/dev/null 2>&1; then
    jq -n --arg slug "$slug" --arg image "$image" --arg version "$version" --arg ts "$timestamp" \
      '{slug: $slug, image: $image, upstream_version: $version, last_update: $ts}' > "$updater_file"
    log "$COLOR_YELLOW" "🆕 Created updater.json for $slug"
  else
    # Update existing file
    jq --arg version "$version" --arg ts "$timestamp" \
      '.upstream_version = $version | .last_update = $ts' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"
    log "$COLOR_GREEN" "✅ Updated updater.json for $slug"
  fi
}

fix_changelog() {
  local changelog_file="$1"
  local slug="$2"
  local current_version="$3"
  local source_url="$4"

  if [ ! -f "$changelog_file" ] || ! grep -q "^CHANGELOG for $slug" "$changelog_file"; then
    {
      echo "CHANGELOG for $slug"
      echo "==================="
      echo
      echo "Initial version: $current_version"
      echo "Docker Image source: $source_url"
      echo
    } > "$changelog_file"
    log "$COLOR_YELLOW" "🆕 Created CHANGELOG.md for $slug"
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    [ "$arch" == "x86_64" ] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
  fi

  local slug
  if [ -f "$config_file" ]; then
    slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  fi
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" | tr -d '\n\r ')
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")
  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  local source_url
  source_url=$(get_docker_source_url "$image")

  local timestamp
  timestamp=$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')

  fix_changelog "$changelog_file" "$slug" "$current_version" "$source_url"

  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file")
  fi

  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update config.json version
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
    fi

    fix_updater_json "$updater_file" "$slug" "$image" "$latest_version" "$timestamp"

    # Update CHANGELOG.md - prepend new entry
    local new_entry="v$latest_version ($timestamp)
    Update from version $current_version to $latest_version (image: $image)

"
    {
      head -n 2 "$changelog_file"
      echo "$new_entry"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"
    notify "Updated $slug from $current_version to $latest_version" "Add-on Updater"
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

get_docker_source_url() {
  local image="$1"
  if [[ "$image" =~ ^linuxserver/ ]]; then
    echo "https://github.com/linuxserver/docker-$image"
  elif [[ "$image" =~ ^lscr\.io/linuxserver/ ]]; then
    echo "https://github.com/linuxserver/docker-$image"
  elif [[ "$image" =~ ^ghcr\.io/ ]]; then
    echo "https://github.com/$(echo "$image" | cut -d/ -f2-4)"
  elif [[ "$image" =~ ^gitun\.io/ ]]; then
    echo "https://gitun.io/$(echo "$image" | cut -d/ -f2-)"
  else
    echo "https://hub.docker.com/r/$image"
  fi
}

perform_update_check() {
  clone_or_update_repo
  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      update_addon_if_needed "$addon_path"
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
      notify "Git push successful with updates." "Add-on Updater"
    else
      log "$COLOR_RED" "❌ Git push failed."
      notify "Git push failed!" "Add-on Updater ERROR"
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

cronnext() {
  # Usage: cronnext "<cron_expr>" "<timezone>"
  # Returns the Unix timestamp of the next cron execution time

  local cron_expr="$1"
  local tz="$2"

  if command -v python3 >/dev/null 2>&1; then
    python3 -c "
import sys
from croniter import croniter
from datetime import datetime
import pytz

cron = sys.argv[1]
tz = sys.argv[2]

now = datetime.now(pytz.timezone(tz))
iter = croniter(cron, now)
next_time = iter.get_next(datetime)
print(int(next_time.timestamp()))
" "$cron_expr" "$tz"
  else
    # fallback: run daily at 2am local time
    echo $(( $(date +%s) + 86400 ))
  fi
}

run_cron_loop() {
  while true; do
    local now_ts next_ts sleep_sec next_run_formatted

    now_ts=$(date +%s)
    next_ts=$(cronnext "$CHECK_CRON" "$TIMEZONE")

    sleep_sec=$((next_ts - now_ts))
    if [ "$sleep_sec" -le 0 ]; then
      sleep_sec=60  # minimum wait
    fi

    next_run_formatted=$(TZ="$TIMEZONE" date -d "@$next_ts" '+%Y-%m-%d %H:%M:%S %Z')

    log "$COLOR_PURPLE" "⏳ Sleeping $sleep_sec seconds until next scheduled run at $next_run_formatted"
    sleep "$sleep_sec"
    log "$COLOR_GREEN" "🏃 Running scheduled update check..."
    perform_update_check
  done
}

# Main start
if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  notify "ERROR: Config file $CONFIG_PATH not found!" "Add-on Updater ERROR"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."

perform_update_check
log "$COLOR_GREEN" "⏳ Waiting for scheduled cron runs..."

run_cron_loop
