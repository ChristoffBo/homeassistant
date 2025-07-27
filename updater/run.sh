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

  local gotify_url
  gotify_url=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
  local gotify_token
  gotify_token=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
  local mailrise_url
  mailrise_url=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
  local mailrise_token
  mailrise_token=$(jq -r '.mailrise.token // empty' "$CONFIG_PATH")
  local apprise_url
  apprise_url=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")

  if [ -n "$gotify_url" ] && [ -n "$gotify_token" ]; then
    curl -s -X POST "$gotify_url/message?token=$gotify_token" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"message\":\"$message\",\"priority\":5}" >/dev/null 2>&1
  fi

  if [ -n "$mailrise_url" ] && [ -n "$mailrise_token" ]; then
    curl -s -X POST "$mailrise_url/api/notification" \
      -H "Authorization: Bearer $mailrise_token" \
      -H "Content-Type: application/json" \
      -d "{\"message\":\"$message\",\"title\":\"$title\"}" >/dev/null 2>&1
  fi

  if [ -n "$apprise_url" ]; then
    curl -s -X POST "$apprise_url" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"body\":\"$message\"}" >/dev/null 2>&1
  fi
}

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

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Cloning repository..."
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR" >>"$LOG_FILE" 2>&1; then
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
    if git pull "$GIT_AUTH_REPO" main >>"$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git pull successful."
      notify "Git pull successful." "Add-on Updater"
    else
      log "$COLOR_RED" "❌ Git pull failed."
      notify "Git pull failed." "Add-on Updater ERROR"
    fi
  fi
}

# Fetch latest Docker Hub tag safely
fetch_latest_dockerhub_tag() {
  local image="$1"
  local repo tag

  # Strip registry prefix if any (like docker.io/), and tag
  repo="${image#*/}"
  repo="${repo%:*}"

  # Query Docker Hub API, safely handle missing or empty results
  tag=$(curl -s "https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100" | \
    jq -r '
      if (.results | type == "array") then
        .results[].name
        | select(. != "latest")
      else
        empty
      end
    ' | sort -V | tail -n1)

  if [ -z "$tag" ]; then
    tag="latest"
  fi

  echo "$tag"
}

# Fetch latest GitHub Container Registry tag
fetch_latest_github_tag() {
  local image="$1"
  # Remove 'ghcr.io/' prefix
  local repo="${image#ghcr.io/}"
  local api_url="https://api.github.com/orgs/linuxserver/packages/container/${repo}/versions"

  tag=$(curl -s "$api_url" | jq -r '.[0].metadata.container.tags[0]' 2>/dev/null)

  if [ -z "$tag" ]; then
    tag="latest"
  fi

  echo "$tag"
}

# Fetch latest LinuxServer tag (simulate here, replace with real logic if API available)
fetch_latest_linuxserver_tag() {
  local image="$1"
  # For now just return "latest"
  echo "latest"
}

get_latest_tag() {
  local image="$1"
  if [[ "$image" =~ ^ghcr.io/ ]]; then
    fetch_latest_github_tag "$image"
  elif [[ "$image" =~ ^linuxserver/ ]] || [[ "$image" =~ ^lscr.io/linuxserver/ ]]; then
    fetch_latest_linuxserver_tag "$image"
  else
    fetch_latest_dockerhub_tag "$image"
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ] && [ ! -f "$updater_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json, build.json, and updater.json, skipping."
    return
  fi

  local image=""
  local slug=""
  local current_version=""

  # Try build.json first for image
  if [ -f "$build_file" ]; then
    local arch
    arch=$(uname -m)
    [ "$arch" == "x86_64" ] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from' "$build_file" 2>/dev/null)
    slug=$(jq -r '.slug // empty' "$build_file" 2>/dev/null)
    current_version=$(jq -r '.version // empty' "$build_file" 2>/dev/null)
  fi

  # fallback to config.json
  if [ -z "$image" ] || [ "$image" == "null" ]; then
    if [ -f "$config_file" ]; then
      image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
      slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
      current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null)
    fi
  fi

  # fallback to updater.json (for slug and version)
  if [ -f "$updater_file" ]; then
    if [ -z "$slug" ] || [ "$slug" == "null" ]; then
      slug=$(jq -r '.slug // empty' "$updater_file" 2>/dev/null)
    fi
    if [ -z "$current_version" ] || [ "$current_version" == "null" ]; then
      current_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
    fi
  fi

  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' missing image field, skipping."
    return
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  local latest_version
  latest_version=$(get_latest_tag "$image")

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  local timestamp
  timestamp=$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')

  # Check if changelog is valid, create/fix if missing or broken
  if [ ! -f "$changelog_file" ] || ! grep -q "^CHANGELOG for $slug" "$changelog_file"; then
    {
      echo "CHANGELOG for $slug"
      echo "==================="
      echo
      echo "Initial version: $current_version"
      echo "Docker Image source: $image"
      echo
    } >"$changelog_file"
    log "$COLOR_YELLOW" "🆕 Created or fixed CHANGELOG.md for $slug"
  fi

  # Read last update from updater.json
  local last_update="N/A"
  if [ -f "$updater_file" ] && jq -e . "$updater_file" >/dev/null 2>&1; then
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file")
  fi

  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update version in config.json or build.json
    if [ -f "$config_file" ] && jq -e . "$config_file" >/dev/null 2>&1; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" >"$config_file.tmp" && mv "$config_file.tmp" "$config_file"
    elif [ -f "$build_file" ] && jq -e . "$build_file" >/dev/null 2>&1; then
      jq --arg v "$latest_version" '.version = $v' "$build_file" >"$build_file.tmp" && mv "$build_file.tmp" "$build_file"
    fi

    # Update updater.json or create it if missing
    if [ -f "$updater_file" ] && jq -e . "$updater_file" >/dev/null 2>&1; then
      jq --arg v "$latest_version" --arg dt "$timestamp" --arg img "$image" \
        '.upstream_version = $v | .last_update = $dt | .image = $img' "$updater_file" >"$updater_file.tmp"
    else
      jq -n --arg slug "$slug" --arg img "$image" --arg v "$latest_version" --arg dt "$timestamp" \
        '{slug: $slug, image: $img, upstream_version: $v, last_update: $dt}' >"$updater_file.tmp"
    fi
    mv "$updater_file.tmp" "$updater_file"

    # Update CHANGELOG.md by prepending new entry
    local new_entry="v$latest_version ($timestamp)
    Update from version $current_version to $latest_version (image: $image)

"
    {
      head -n 2 "$changelog_file"
      echo "$new_entry"
      tail -n +3 "$changelog_file"
    } >"$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ Updated updater.json and CHANGELOG.md for $slug"
    notify "Updated $slug from $current_version to $latest_version" "Add-on Updater"
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo
  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local changes_made=0

  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      update_addon_if_needed "$addon_path" && changes_made=1
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >>"$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >>"$LOG_FILE" 2>&1; then
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

get_next_run_time() {
  # Use croniter python package if installed, else fallback to cronnext
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<EOF 2>/dev/null
import sys
from datetime import datetime
from croniter import croniter
cron_expr = sys.argv[1]
tz = sys.argv[2]
now = datetime.now()
iter = croniter(cron_expr, now)
next_run = iter.get_next(datetime)
print(next_run.strftime("%H:%M"))
EOF
  else
    # fallback: just show the cron string (hours and minutes fields)
    echo "$CHECK_CRON" | awk '{print $2 ":" $1}'
  fi
}

log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater..."
log "$COLOR_GREEN" "🚀 Initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "⏰ Next scheduled run at: $(get_next_run_time)"

perform_update_check

log "$COLOR_GREEN" "⏳ Waiting for cron trigger..."

# Cron loop: sleep 60s, check current time against cron schedule (hours and minutes)
while true; do
  current_time=$(TZ="$TIMEZONE" date '+%H:%M')
  next_run=$(get_next_run_time)
  if [ "$current_time" == "$next_run" ]; then
    log "$COLOR_GREEN" "⏰ Cron triggered at $current_time"
    perform_update_check
  fi
  sleep 60
done
