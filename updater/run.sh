#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Colors for log output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  # Timestamp with same color as message
  local timestamp
  timestamp=$(date +"[%Y-%m-%d %H:%M:%S %Z]")
  echo -e "${color}${timestamp} $*${COLOR_RESET}"
  echo -e "${timestamp} $*" >> "$LOG_FILE"
}

log_next_cron() {
  local cron_expr="$1"
  local tz="$2"

  local next_run
  if command -v python3 >/dev/null 2>&1; then
    next_run=$(python3 - << EOF
import sys
from croniter import croniter
from datetime import datetime
import pytz

cron = sys.argv[1]
tz = sys.argv[2]

base = datetime.now(pytz.utc)
iter = croniter(cron, base)
nextrun = iter.get_next(datetime)

if tz:
    tzinfo = pytz.timezone(tz)
    nextrun = nextrun.astimezone(tzinfo)

print(nextrun.strftime('%Y-%m-%d %H:%M:%S %Z'))
EOF
    "$cron_expr" "$tz" 2>/dev/null || echo "unknown")
  else
    next_run="unknown"
  fi

  if [ "$next_run" != "unknown" ]; then
    log "$COLOR_GREEN" "⏳ Waiting for cron to trigger... Next run at: $next_run"
  else
    log "$COLOR_GREEN" "⏳ Waiting for cron to trigger... (next run time unavailable)"
  fi
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Read config options
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH") # default UTC if empty

# Setup git repo URL with auth if provided
GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Clear log file before each run
> "$LOG_FILE"

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📥 Cloning repository $GITHUB_REPO..."
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
      exit 1
    fi
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=10&ordering=last_updated"
  local tags_json
  tags_json=$(curl -s "$url")
  local tag
  tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | head -n 1)
  if [ -n "$tag" ]; then
    echo "$tag"
  else
    echo "latest"
  fi
}

fetch_latest_linuxserver_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local tag
  tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
  if [ -n "$tag" ] && [ "$tag" != "null" ]; then
    echo "$tag"
  else
    echo ""
  fi
}

fetch_latest_ghcr_tag() {
  local image="$1"
  local repo_path="${image#ghcr.io/}"
  local url="https://ghcr.io/v2/${repo_path}/tags/list"
  local tags_json
  tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null)
  local tag
  tag=$(echo "$tags_json" | jq -r '.tags[-1]' 2>/dev/null)
  if [ -n "$tag" ] && [ "$tag" != "null" ]; then
    echo "$tag"
  else
    echo ""
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"

  if [[ "$image_no_tag" == lscr.io/linuxserver/* ]]; then
    image_no_tag="${image_no_tag#lscr.io/}"
  fi

  if [[ "$image_no_tag" == linuxserver/* ]]; then
    echo "$(fetch_latest_linuxserver_tag "$image_no_tag")"
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    echo "$(fetch_latest_ghcr_tag "$image_no_tag")"
  else
    echo "$(fetch_latest_dockerhub_tag "$image_no_tag")"
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no config.json or build.json, skipping."
    return 1
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch
    arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return 1
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "🚀 Latest version: Checking..."

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  local last_updated="N/A"
  if [ -f "$updater_file" ]; then
    last_updated=$(jq -r '.last_update // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "🕒 Last updated: ${last_updated:-N/A}"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update config.json version
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    # Update updater.json
    jq --arg v "$latest_version" --arg dt "$(date +"%d-%m-%Y %H:%M")" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +"%d-%m-%Y %H:%M")" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    # Ensure CHANGELOG.md exists and prepend changelog
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "🆕 Created new CHANGELOG.md for $slug"
    fi

    # Determine source URL for image (dockerhub/linuxserver/ghcr)
    local source_url=""
    if [[ "$image" == linuxserver/* ]] || [[ "$image" == lscr.io/linuxserver/* ]]; then
      source_url="https://hub.docker.com/r/${image#lscr.io/}"
    elif [[ "$image" == ghcr.io/* ]]; then
      source_url="https://github.com/${image#ghcr.io/}"
    else
      source_url="https://hub.docker.com/r/$image"
    fi

    local new_entry="v$latest_version ($(date +"%d-%m-%Y %H:%M"))
    Update from version $current_version to $latest_version (image: $image)
    Source: $source_url

"

    # Prepend new entry after header (2 lines)
    {
      head -n 2 "$changelog_file"
      echo "$new_entry"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    return 0
  else
    log "$COLOR_BLUE" "✔️ $slug is already up to date ($current_version)"
    return 1
  fi
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updated=0

  log "$COLOR_BLUE" "🔍 Checking add-ons in $REPO_DIR..."

  for addon_path in "$REPO_DIR"/*/; do
    # Make sure path is directory
    if [ ! -d "$addon_path" ]; then
      continue
    fi

    update_addon_if_needed "$addon_path"
    if [ $? -eq 0 ]; then
      updated=$((updated+1))
    fi
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Update add-on versions automatically" >> "$LOG_FILE" 2>&1 || true

    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed. Check authentication and remote URL."
    fi
  else
    if [ $updated -eq 0 ]; then
      log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
    else
      log "$COLOR_BLUE" "📦 No git changes to commit."
    fi
  fi
}

# Initial startup logs
log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."

perform_update_check

# Start cron daemon in background
crond -f -L /dev/stdout &

while true; do
  log_next_cron "$CHECK_CRON" "$TIMEZONE"
  sleep 60
done
