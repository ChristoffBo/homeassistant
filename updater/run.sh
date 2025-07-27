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

# Load config values or exit
if [ ! -f "$CONFIG_PATH" ]; then
  echo -e "${COLOR_RED}ERROR: Config file $CONFIG_PATH not found!${COLOR_RESET}"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time // empty' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

LOG_FILE="/data/updater.log"
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  local timestamp
  timestamp=$(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')
  echo -e "[$timestamp] ${color}$*${COLOR_RESET}"
}

clone_or_update_repo() {
  log "$COLOR_BLUE" "🔄 Pulling latest changes from GitHub..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "📂 Repo not found locally. Cloning..."
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      exit 1
    fi
  else
    cd "$REPO_DIR"
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository pull successful."
    else
      log "$COLOR_RED" "❌ Failed to pull latest changes."
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
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local updater_file="$addon_path/updater.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  # Check if addon has config.json or build.json
  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return 1
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch
    arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi
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

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
  fi

  local last_update="unknown"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: ${current_version:-unknown}"
  log "$COLOR_BLUE" "🚀 Latest version: Checking..."
  log "$COLOR_BLUE" "🕒 Last updated: ${last_update:-unknown}"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️ Updating $slug from $current_version to $latest_version"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    jq --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
    mv "$updater_file.tmp" "$updater_file"

    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "📝 Created new CHANGELOG.md for $slug"
    fi

    local NEW_ENTRY="v$latest_version ($(TZ="$TIMEZONE" date +'%d-%m-%Y %H:%M'))
    Updated from version $current_version to $latest_version (image: $image)

"

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

  cd "$REPO_DIR" || {
    log "$COLOR_RED" "❌ Cannot cd to $REPO_DIR"
    exit 1
  }

  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updated=0
  local total=0

  log "$COLOR_BLUE" "🔍 Checking add-ons in $REPO_DIR..."

  for addon_path in "$REPO_DIR"/*/; do
    if [ -d "$addon_path" ]; then
      total=$((total + 1))
      log "$COLOR_BLUE" "📁 Found add-on folder: $addon_path"
      if update_addon_if_needed "$addon_path"; then
        updated=$((updated + 1))
      fi
    fi
  done

  if [ "$updated" -gt 0 ]; then
    log "$COLOR_GREEN" "📝 $updated add-on(s) updated, committing changes..."
    git add .
    if git commit -m "⬆️ Update $updated add-on(s) versions" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git commit successful."
    else
      log "$COLOR_YELLOW" "⚠️ Nothing to commit or commit failed."
    fi

    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed."
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi

  log "$COLOR_BLUE" "📊 Checked $total add-on(s)."
}

log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
if [ -z "$CHECK_TIME" ] || ! [[ "$CHECK_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  log "$COLOR_YELLOW" "⚠️ Invalid or missing check_time, defaulting to 02:00"
  CHECK_TIME="02:00"
fi
log "$COLOR_BLUE" "📅 Scheduled daily at $CHECK_TIME ($TIMEZONE)"

log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check

log "$COLOR_GREEN" "⏳ Waiting for cron to trigger..."

CRON_MIN=${CHECK_TIME#*:}
CRON_HOUR=${CHECK_TIME%%:*}

echo "$CRON_MIN $CRON_HOUR * * * /run.sh run >> /data/updater.log 2>&1" > /etc/crontabs/root
crond -f -L /data/updater.log
