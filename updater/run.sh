#!/usr/bin/env bash
set -eo pipefail

export HOME=/tmp

CONFIG_FILE="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"

github_repo=$(jq -r '.github_repo // empty' "$CONFIG_FILE")
github_username=$(jq -r '.github_username // empty' "$CONFIG_FILE")
github_token=$(jq -r '.github_token // empty' "$CONFIG_FILE")
gitea_repo=$(jq -r '.gitea_repo // empty' "$CONFIG_FILE")
gitea_username=$(jq -r '.gitea_username // empty' "$CONFIG_FILE")
gitea_token=$(jq -r '.gitea_token // empty' "$CONFIG_FILE")

timezone=$(jq -r '.timezone // "UTC"' "$CONFIG_FILE")
dry_run=$(jq -r '.dry_run // false' "$CONFIG_FILE")
skip_push=$(jq -r '.skip_push // false' "$CONFIG_FILE")
debug=$(jq -r '.debug // false' "$CONFIG_FILE")

notifications_enabled=$(jq -r '.notifications_enabled // false' "$CONFIG_FILE")
notification_service=$(jq -r '.notification_service // ""' "$CONFIG_FILE")
notification_url=$(jq -r '.notification_url // ""' "$CONFIG_FILE")
notification_token=$(jq -r '.notification_token // ""' "$CONFIG_FILE")
notification_to=$(jq -r '.notification_to // ""' "$CONFIG_FILE")
notify_on_success=$(jq -r '.notify_on_success // false' "$CONFIG_FILE")
notify_on_error=$(jq -r '.notify_on_error // false' "$CONFIG_FILE")
notify_on_updates=$(jq -r '.notify_on_updates // false' "$CONFIG_FILE")

export TZ="$timezone"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() {
  local type="$1"
  local msg="$2"
  local color="$3"
  local timestamp
  timestamp=$(date +"[%Y-%m-%d %H:%M:%S %Z]")
  echo -e "${timestamp} ${color}${type}${NC} $msg"
}

info() { log "ℹ️" "$1" "$CYAN"; }
warn() { log "⚠️" "$1" "$YELLOW"; }
error() { log "❌" "$1" "$RED"; }
success() { log "✅" "$1" "$GREEN"; }
debug_log() {
  if [ "$debug" = "true" ]; then
    log "🐛" "$1" "$YELLOW"
  fi
}

git_clone_or_pull() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    info "Cloning repository..."
    if [ -n "$github_token" ] && [ -n "$github_username" ] && [ -n "$github_repo" ]; then
      git clone "https://${github_username}:${github_token}@${github_repo#https://}" "$REPO_DIR"
    elif [ -n "$gitea_token" ] && [ -n "$gitea_username" ] && [ -n "$gitea_repo" ]; then
      git clone "https://${gitea_username}:${gitea_token}@${gitea_repo#https://}" "$REPO_DIR"
    else
      git clone "$github_repo" "$REPO_DIR"
    fi
  else
    info "Using existing repo at $REPO_DIR"
    cd "$REPO_DIR"
    info "Pulling latest changes from repository..."
    git pull --ff-only || true
  fi
}

normalize_version() {
  # Strip arch prefixes and leading 'v'
  echo "$1" | sed -E 's/^(amd64-|armhf-|armv7-|arm64v8-)//' | sed 's/^v//'
}

is_semver() {
  # Returns 0 (true) if version matches semver-ish, else 1
  [[ "$1" =~ ^[0-9]+(\.[0-9]+){0,2}(-[a-z0-9]+)?$ ]]
}

version_lt() {
  # If either version is not semver, treat current < latest only if current is empty or not semver
  if ! is_semver "$1" || ! is_semver "$2"; then
    # Consider non-semver current version always less (force update)
    if ! is_semver "$1"; then
      return 0
    else
      return 1
    fi
  fi
  [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" != "$2" ]
}

fetch_tags() {
  local docker_image="$1"
  local tags_json
  local available_tags

  # Replace {arch} placeholders with amd64 for tag fetch
  docker_image="${docker_image//\{arch\}/amd64}"

  if [[ "$docker_image" =~ ^ghcr.io/ ]]; then
    local repo_path="${docker_image#ghcr.io/}"
    # Remove arch suffix if present
    repo_path="${repo_path%-amd64}"
    local tags_url="https://ghcr.io/v2/${repo_path}/tags/list"
    debug_log "Fetching tags from GHCR: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    if [ -z "$tags_json" ] || ! echo "$tags_json" | jq -e '.' >/dev/null 2>&1; then
      warn "Failed to fetch or parse tags from GHCR for $docker_image"
      echo ""
      return
    fi
    available_tags=$(echo "$tags_json" | jq -r '.tags[]?' || echo "")
  elif [[ "$docker_image" =~ ^lscr.io/ ]]; then
    local repo_path="${docker_image#lscr.io/}"
    repo_path="${repo_path%:*}"
    local tags_url="https://registry.hub.docker.com/v2/repositories/linuxserver/${repo_path}/tags?page_size=100"
    debug_log "Fetching tags from LinuxServer.io: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    if [ -z "$tags_json" ] || ! echo "$tags_json" | jq -e '.' >/dev/null 2>&1; then
      warn "Failed to fetch or parse tags from LinuxServer.io for $docker_image"
      echo ""
      return
    fi
    available_tags=$(echo "$tags_json" | jq -r '.results[].name' || echo "")
  else
    local image_path="${docker_image#docker.io/}"
    if [[ "$image_path" != */* ]]; then
      image_path="library/$image_path"
    fi
    local tags_url="https://registry.hub.docker.com/v2/repositories/${image_path}/tags?page_size=100"
    debug_log "Fetching tags from Docker Hub: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    if [ -z "$tags_json" ] || ! echo "$tags_json" | jq -e '.' >/dev/null 2>&1; then
      warn "Failed to fetch or parse tags from Docker Hub for $docker_image"
      echo ""
      return
    fi
    available_tags=$(echo "$tags_json" | jq -r '.results[].name' || echo "")
  fi

  echo "$available_tags"
}

send_gotify_notification() {
  local title="$1"
  local message="$2"
  if [ "$notifications_enabled" != "true" ] || [ "$notification_service" != "gotify" ]; then
    debug_log "Skipping Gotify notification - disabled or not configured"
    return
  fi
  local payload
  payload=$(jq -n \
    --arg title "$title" \
    --arg message "$message" \
    --arg priority "0" \
    '{title: $title, message: $message, priority: ($priority|tonumber)}')
  debug_log "Sending Gotify notification to $notification_url"
  curl -s -X POST \
    -H "X-Gotify-Key: $notification_token" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$notification_url/message?token=$notification_token" >/dev/null 2>&1 && success "Gotify notification sent" || warn "Gotify notification failed"
}

send_notification() {
  local title="$1"
  local message="$2"
  if [ "$notification_service" = "gotify" ]; then
    send_gotify_notification "$title" "$message"
  else
    debug_log "Notification service $notification_service not implemented"
  fi
}

info "🔁 Home Assistant Add-on Updater Starting"

info "========= CONFIGURATION =========="
info "GitHub Repo: $github_repo"
info "Gitea Repo: $gitea_repo"
info "Dry Run: $dry_run"
info "Skip Push: $skip_push"
info "Timezone: $timezone"
info "Debug Mode: $debug"
info "Notifications Enabled: $notifications_enabled"
info "Notification Service: $notification_service"
info "Notify on Success: $notify_on_success"
info "Notify on Error: $notify_on_error"
info "Notify on Updates: $notify_on_updates"
info "=================================="

git_clone_or_pull

info "Git pull completed."

cd "$REPO_DIR"

updates_found=0
updates_msg="Add-on Update Summary\n"

# Scan all top-level folders (ignore hidden and files)
for addon_dir in */; do
  [[ "$addon_dir" =~ ^\..* ]] && continue
  [ ! -d "$addon_dir" ] && continue

  addon_name="${addon_dir%/}"
  info "Checking add-on: $addon_name"

  config_file="$REPO_DIR/$addon_dir/config.json"
  build_file="$REPO_DIR/$addon_dir/build.json"
  updater_file="$REPO_DIR/$addon_dir/updater.json"

  if [ ! -f "$config_file" ]; then
    warn "Add-on $addon_name missing config.json, skipping."
    continue
  fi

  docker_image=$(jq -r '.image // empty' "$config_file")
  if [ -z "$docker_image" ] && [ -f "$build_file" ]; then
    docker_image=$(jq -r '.image // empty' "$build_file")
  fi
  if [ -z "$docker_image" ] && [ -f "$updater_file" ]; then
    docker_image=$(jq -r '.image // empty' "$updater_file")
  fi

  if [ -z "$docker_image" ]; then
    warn "Add-on $addon_name has no Docker image defined, skipping."
    continue
  fi

  current_version=""
  if [ -f "$updater_file" ]; then
    current_version=$(jq -r '.version // empty' "$updater_file")
  fi
  if [ -z "$current_version" ] && [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file")
  fi
  if [ -z "$current_version" ]; then
    current_version="latest"
  fi

  debug_log "Current version: $current_version"
  debug_log "Docker image: $docker_image"

  available_tags=$(fetch_tags "$docker_image")

  if [ -z "$available_tags" ]; then
    warn "Could not retrieve tags for $docker_image"
    continue
  fi

  # Filter tags to only semantic version-like tags, fallback to all tags
  filtered_tags=$(echo "$available_tags" | grep -vE '^latest$' | grep -E '^[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-z0-9]+)?$' || true)
  if [ -z "$filtered_tags" ]; then
    filtered_tags="$available_tags"
  fi

  latest_version=""
  latest_tag=""
  for tag in $filtered_tags; do
    norm_tag=$(normalize_version "$tag")
    if [ -z "$latest_version" ] || version_lt "$latest_version" "$norm_tag"; then
      latest_version="$norm_tag"
      latest_tag="$tag"
    fi
  done

  if [ -z "$latest_tag" ]; then
    warn "Could not determine latest version tag for $docker_image"
    continue
  fi

  norm_current=$(normalize_version "$current_version")
  debug_log "Latest available version: $latest_tag (normalized: $latest_version)"
  debug_log "Normalized current version: $norm_current"

  if version_lt "$norm_current" "$latest_version"; then
    info "Add-on $addon_name update available: $current_version -> $latest_tag"

    if [ "$dry_run" = "true" ]; then
      info "Dry run enabled, skipping update for $addon_name"
    else
      now_ts=$(date +"%Y-%m-%d %H:%M:%S %Z")
      # Update updater.json (create if missing)
      if [ -f "$updater_file" ]; then
        jq --arg v "$latest_tag" --arg t "$now_ts" '.version = $v | .last_updated = $t' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"
      else
        echo "{\"version\":\"$latest_tag\",\"last_updated\":\"$now_ts\"}" > "$updater_file"
      fi

      # Update config.json version field
      jq --arg v "$latest_tag" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

      info "Updated $addon_name to version $latest_tag"
      updates_found=$((updates_found + 1))
      updates_msg+="✅ $addon_name: $current_version -> $latest_tag\n"
    fi
  else
    info "Add-on $addon_name already up to date ($current_version)"
    updates_msg+="✅
