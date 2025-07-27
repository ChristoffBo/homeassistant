#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  local timestamp
  timestamp=$(TZ=UTC date '+%Y-%m-%d %H:%M:%S UTC')
  echo -e "[$timestamp] ${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time // empty' "$CONFIG_PATH")  # Format HH:MM

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  # Insert credentials into repo URL for push/pull auth
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

LOG_FILE="/data/updater.log"
: > "$LOG_FILE"

clone_or_update_repo() {
  log "$COLOR_BLUE" "🔄 Pulling latest changes from GitHub..."
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_BLUE" "📥 Cloning repository because local repo not found..."
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ ERROR cloning repository."
      exit 1
    fi
  else
    cd "$REPO_DIR"
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository pull successful."
    else
      log "$COLOR_RED" "❌ ERROR pulling repository."
      exit 1
    fi
  fi

  # List add-on folders found after sync
  log "$COLOR_BLUE" "📂 Listing add-on folders in $REPO_DIR:"
  for d in "$REPO_DIR"/*/; do
    if [ -d "$d" ]; then
      log "$COLOR_BLUE" " - $(basename "$d")"
    fi
  done
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

  # Fix for lscr.io/linuxserver/ images to map to linuxserver/ on Docker Hub API
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
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local updater_file="$addon_path/updater.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  # Check existence of config.json or build.json; skip if neither
  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return 1
  fi

  local image=""
  # Prefer build.json image if exists (with arch selection)
  if [ -f "$build_file" ]; then
    local arch
    arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  # Fallback to config.json image
  if [ -z "$image" ] || [ "$image" == "null" ]; then
    if [ -f "$config_file" ]; then
      image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
    fi
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return 1
  fi

  local slug
  if [ -f "$config_file" ]; then
    slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  fi
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  # Current version from config.json
  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  # Upstream version from updater.json
  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: ${current_version:-unknown}"
  log "$COLOR_BLUE" "🚀 Latest version: Checking..."

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")
  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  # Last updated from updater.json, fallback to unknown
  local last_update="unknown"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"
  log "$COLOR_BLUE" "🕒 Last updated: ${last_update:-unknown}"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️ Updating $slug from $current_version to $latest_version"

    # Update version in config.json
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    # Update updater.json (create if missing)
    jq --arg v "$latest_version" --arg dt "$(date -u +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date -u +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
    mv "$updater_file.tmp" "$updater_file"

    # Create or update CHANGELOG.md
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "📝 Created new CHANGELOG.md for $slug"
    fi

    local NEW_ENTRY="v$latest_version ($(date -u +'%d-%m-%Y %H:%M'))
    Updated from version $current_version to $latest_version (image: $image)

"

    # Prepend new entry after header (2 lines)
    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
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
  local checked=0

  log "$COLOR_BLUE" "🔍 Checking add-ons in $REPO_DIR..."

  for addon_path in "$REPO_DIR"/*/; do
    if [ -d "$addon_path" ]; then
      checked=$((checked + 1))
      update_addon_if_needed "$addon_path" && updated=$((updated + 1))
    fi
  done

  if [ "$checked" -eq 0 ]; then
    log "$COLOR_YELLOW" "⚠️ No add-ons found in $REPO_DIR"
  fi

  if [ "$updated" -gt 0 ]; then
    log "$COLOR_BLUE" "💾 Committing $updated updated add-ons..."
    git add .
    if git commit -m "⬆️ Update addon(s) version(s)" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Commit successful."
      if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "🚀 Git push successful."
      else
        log "$COLOR_RED" "❌ Git push failed."
      fi
    else
      log "$COLOR_RED" "❌ Git commit failed."
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

# Start here

log "$COLOR_GREEN" "🚀 Add-on Updater initialized"

if [ -z "$CHECK_TIME" ] || ! [[ "$CHECK_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  log "$COLOR_YELLOW" "⚠️ Invalid or missing check_time in config, defaulting to 02:00 UTC"
  CHECK_TIME="02:00"
fi

log "$COLOR_BLUE" "📅 Scheduled_
