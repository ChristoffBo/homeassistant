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
  # Print timestamp in same color
  local timestamp
  timestamp=$(date "+[%Y-%m-%d %H:%M:%S %Z]")
  echo -e "${color}${timestamp} $*${COLOR_RESET}"
  echo -e "${timestamp} $*" >> "$LOG_FILE"
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

# Validate CHECK_CRON fallback
if [ -z "$CHECK_CRON" ] || [ "$CHECK_CRON" == "null" ]; then
  CHECK_CRON="0 3 * * *"
fi

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Clear log before each run
: > "$LOG_FILE"

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Repo not found locally. Cloning..."
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

  # Skip if no config.json and no build.json
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

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
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

  local last_update=""
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // empty' "$updater_file" 2>/dev/null)
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
  if [ -n "$last_update" ]; then
    log "$COLOR_BLUE" "🕒 Last updated: $last_update"
  fi

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️ Updating $slug from $current_version to $latest_version"

    # Update config.json version
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    mv "$config_file.tmp" "$config_file"

    # Update updater.json or create it
    if [ ! -f "$updater_file" ]; then
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ=$TIMEZONE date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file"
      log "$COLOR_YELLOW" "🆕 Created new updater.json for $slug"
    else
      jq --arg v "$latest_version" --arg dt "$(TZ=$TIMEZONE date +'%d-%m-%Y %H:%M')" \
        '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null
      mv "$updater_file.tmp" "$updater_file"
    fi

    # Create or prepend changelog entry
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "🆕 Created new CHANGELOG.md for $slug"
    fi

    local new_entry
    new_entry="v$latest_version ($(TZ=$TIMEZONE date +'%d-%m-%Y %H:%M'))\n    Update from $current_version to $latest_version (image: $image)\n"

    {
      head -n 2 "$changelog_file"
      echo -e "$new_entry"
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

  local updates_found=0

  log "$COLOR_BLUE" "🔍 Checking add-ons in $REPO_DIR..."
  for addon_path in "$REPO_DIR"/*/; do
    if update_addon_if_needed "$addon_path"; then
      updates_found=$((updates_found + 1))
    fi
  done

  if [ "$updates_found" -gt 0 ]; then
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

setup_cron() {
  echo "$CHECK_CRON TZ=$TIMEZONE /run.sh run >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
  crond -f -L /proc/1/fd/1 &
  log "$COLOR_BLUE" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
}

main() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  perform_update_check
  setup_cron

  log "$COLOR_BLUE" "⏳ Waiting for cron to trigger..."
  wait
}

if [ "$1" = "run" ]; then
  perform_update_check
else
  main
fi
