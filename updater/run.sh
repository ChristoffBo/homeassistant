#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  # Timestamp in same color as message
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

# Prepare git repo URL with auth if credentials provided
GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Clear log at start
: > "$LOG_FILE"

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

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=10&ordering=last_updated"
  local tags_json=$(curl -s "$url")
  local tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | head -n 1)
  if [ -n "$tag" ]; then
    echo "$tag"
  else
    echo "latest"
  fi
}

fetch_latest_linuxserver_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
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
  local tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null)
  local tag=$(echo "$tags_json" | jq -r '.tags[-1]' 2>/dev/null)
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
    return
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
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
  log "$COLOR_BLUE" "📦 Image: $image"

  local latest_version="Checking..."
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  # Ensure CHANGELOG.md exists and log creation if new
  if [ ! -f "$changelog_file" ]; then
    echo "CHANGELOG for $slug" > "$changelog_file"
    echo "===================" >> "$changelog_file"
    log "$COLOR_YELLOW" "🆕 Created new CHANGELOG.md for $slug"
  fi

  # Show last update date/time if available
  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update config.json version
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    # Update updater.json
    jq --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    NEW_ENTRY="\
v$latest_version ($(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M'))
    Update from version $current_version to $latest_version (image: $image)

"

    # Prepend new entry after header (2 lines)
    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

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

  local updated=0

  # Find all addon folders containing config.json or build.json or updater.json
  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      update_addon_if_needed "$addon_path" && updated=$((updated+1))
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed."
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."

TZ="$TIMEZONE" cron -f -L 15 -l 8 &

log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check
log "$COLOR_GREEN" "⏳ Waiting for cron to trigger..."

while sleep 60; do :; done
