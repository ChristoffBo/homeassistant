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

log() {
  local color="$1"; shift
  echo -e "${color}[$(TZ="${TZ:-UTC}" date '+%Y-%m-%d %H:%M:%S %Z')] $*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "❌ ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time // "02:00"' "$CONFIG_PATH")
TZ=$(jq -r '.TZ // "UTC"' "$CONFIG_PATH")

CRON_HOUR="${CHECK_TIME%%:*}"
CRON_MINUTE="${CHECK_TIME##*:}"

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

: > "$LOG_FILE"

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_BLUE" "📥 Cloning repository..."
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR" >>"$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      exit 1
    fi
  else
    log "$COLOR_BLUE" "🔄 Pulling latest changes from GitHub..."
    if git -C "$REPO_DIR" pull >>"$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository pull successful."
    else
      log "$COLOR_RED" "❌ Repository pull failed."
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
    fetch_latest_linuxserver_tag "$image_no_tag"
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    fetch_latest_ghcr_tag "$image_no_tag"
  else
    fetch_latest_dockerhub_tag "$image_no_tag"
  fi
}

update_addon_if_needed() {
  local addon_dir="$1"
  local config_file="$addon_dir/config.json"
  local updater_file="$addon_dir/updater.json"
  local changelog_file="$addon_dir/CHANGELOG.md"

  [ ! -f "$config_file" ] && return 0

  local image
  image=$(jq -r '.image // empty' "$config_file")
  [ -z "$image" ] && return 0

  local current_version
  current_version=$(jq -r '.version // ""' "$config_file")
  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  local last_update=""
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // empty' "$updater_file")
  fi
  [ -z "$last_update" ] && last_update="never"

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $(basename "$addon_dir")"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"
  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  if [ "$latest_version" != "" ] && [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "null" ]; then
    log "$COLOR_YELLOW" "⬆️  Updating $(basename "$addon_dir") from $current_version to $latest_version"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    jq -n --arg slug "$(basename "$addon_dir")" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TZ" date '+%d-%m-%Y %H:%M')" \
      '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file"

    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $(basename "$addon_dir")" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "📝 Created new CHANGELOG.md for $(basename "$addon_dir")"
    fi

    NEW_ENTRY="v$latest_version ($(TZ="$TZ" date '+%d-%m-%Y %H:%M'))"

    { head -n 2 "$changelog_file"; echo "$NEW_ENTRY"; echo ""; tail -n +3 "$changelog_file"; } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $(basename "$addon_dir")"

    return 1
  else
    log "$COLOR_GREEN" "✔️ $(basename "$addon_dir") is already up to date ($current_version)"
    return 0
  fi
}

perform_update_check() {
  clone_or_update_repo

  local updates=0
  cd "$REPO_DIR"

  for addon in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon"
    if [ $? -eq 1 ]; then
      updates=$((updates+1))
    fi
  done

  if [ "$updates" -gt 0 ]; then
    log "$COLOR_YELLOW" "📦 $updates add-on(s) updated. Committing and pushing changes..."
    git add .
    if git commit -m "⬆️ Automatic update: bump addon versions" >>"$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git commit successful."
    else
      log "$COLOR_YELLOW" "⚠️ Nothing to commit."
    fi
    if git push >>"$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed."
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

# Set up cron job if not already
setup_cron() {
  local cron_entry="$CRON_MINUTE $CRON_HOUR * * * $0 >> $LOG_FILE 2>&1"
  if ! grep -Fq "$cron_entry" /etc/crontabs/root 2>/dev/null; then
    echo "$cron_entry" >> /etc/crontabs/root
  fi
}

log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_YELLOW" "📅 Scheduled daily at $CHECK_TIME ($TZ)"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check

log "$COLOR_BLUE" "⏳ Waiting for cron to trigger..."

setup_cron

crond -f -L 8
