#!/usr/bin/env bash
set -eo pipefail

CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOCK_FILE="/data/updater.lock"

# Color codes for output
COLOR_RESET="\033[0m"
COLOR_RED="\033[0;31m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[1;33m"
COLOR_BLUE="\033[0;34m"
COLOR_CYAN="\033[0;36m"

# Logging functions
log() {
  local level="$1"
  local color="$2"
  local message="$3"
  local timestamp
  timestamp=$(date +"[%Y-%m-%d %H:%M:%S %Z]")
  echo -e "${timestamp} ${color}${level}${COLOR_RESET} ${message}"
}

info()    { log "ℹ️" "$COLOR_BLUE" "$1"; }
success() { log "✅" "$COLOR_GREEN" "$1"; }
warn()    { log "⚠️" "$COLOR_YELLOW" "$1"; }
error()   { log "❌" "$COLOR_RED" "$1" >&2; }
debug() {
  if [ "$DEBUG" = true ]; then
    log "🐛" "$COLOR_CYAN" "$1"
  fi
}

# Load configuration
if ! command -v jq >/dev/null 2>&1; then
  error "jq not installed"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
GITEA_REPO=$(jq -r '.gitea_repo // empty' "$CONFIG_PATH")
GITEA_TOKEN=$(jq -r '.gitea_token // empty' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
NOTIFICATIONS_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
NOTIFICATION_SERVICE=$(jq -r '.notification_service // empty' "$CONFIG_PATH")
NOTIFICATION_URL=$(jq -r '.notification_url // empty' "$CONFIG_PATH")
NOTIFICATION_TOKEN=$(jq -r '.notification_token // empty' "$CONFIG_PATH")
NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
NOTIFY_ON_ERROR=$(jq -r '.notify_on_error // false' "$CONFIG_PATH")
NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates // false' "$CONFIG_PATH")

export TZ="$TIMEZONE"

info "========== CONFIGURATION =========="
info "GitHub Repo: $GITHUB_REPO"
info "Gitea Repo: $GITEA_REPO"
info "Dry Run: $DRY_RUN"
info "Skip Push: $SKIP_PUSH"
info "Timezone: $TIMEZONE"
info "Debug Mode: $DEBUG"
info "Notifications Enabled: $NOTIFICATIONS_ENABLED"
info "Notification Service: $NOTIFICATION_SERVICE"
info "Notify on Success: $NOTIFY_ON_SUCCESS"
info "Notify on Error: $NOTIFY_ON_ERROR"
info "Notify on Updates: $NOTIFY_ON_UPDATES"
info "==================================="

cd "$REPO_DIR" || { error "Repo directory $REPO_DIR does not exist"; exit 1; }

# Clone or pull repo
if [ ! -d ".git" ]; then
  if [ -n "$GITHUB_REPO" ]; then
    info "Cloning GitHub repo..."
    git clone "https://$GITHUB_USERNAME:$GITHUB_TOKEN@${GITHUB_REPO#https://}" "$REPO_DIR"
  elif [ -n "$GITEA_REPO" ]; then
    info "Cloning Gitea repo..."
    git clone "https://$GITHUB_USERNAME:$GITEA_TOKEN@${GITEA_REPO#https://}" "$REPO_DIR"
  else
    error "No repository URL provided."
    exit 1
  fi
else
  info "Using existing repo at $REPO_DIR"
fi

git config user.name "$GITHUB_USERNAME"
git config user.email "$GITHUB_USERNAME@users.noreply.github.com"

info "Pulling latest changes from repository..."
if ! git pull --rebase; then
  error "Git pull failed"
  [ "$NOTIFY_ON_ERROR" = true ] && send_notification "Add-on Updater Error" "Git pull failed"
  exit 1
fi
info "Git pull completed."

normalize_tag() {
  local tag="$1"
  tag="${tag#amd64-}"
  tag="${tag#armhf-}"
  tag="${tag#arm64-}"
  tag="${tag#aarch64-}"
  tag="${tag#x86_64-}"
  if [ "$tag" = "latest" ] || [ -z "$tag" ]; then
    echo ""
  else
    echo "$tag"
  fi
}

version_lt() {
  [ "$(printf '%s\n%s' "$1" "$2" | sort -V | head -n1)" != "$2" ]
}

extract_current_version() {
  local addon_dir="$1"
  jq -r '.version // empty' "$addon_dir/config.json" 2>/dev/null || echo ""
}

update_changelog() {
  local addon_dir="$1"
  local new_version="$2"
  local changelog_file="$addon_dir/CHANGELOG.md"

  if [ ! -f "$changelog_file" ]; then
    echo "# Changelog" >"$changelog_file"
  fi

  echo -e "\n## $new_version - $(date +"%Y-%m-%d")" >>"$changelog_file"
  echo "- Updated to version $new_version" >>"$changelog_file"
}

send_notification() {
  local title="$1"
  local message="$2"
  if [ "$NOTIFICATIONS_ENABLED" != true ]; then return 0; fi

  case "$NOTIFICATION_SERVICE" in
    gotify)
      if [ -z "$NOTIFICATION_URL" ] || [ -z "$NOTIFICATION_TOKEN" ]; then
        warn "Gotify notification settings incomplete; skipping notification."
        return 1
      fi
      debug "Sending Gotify notification to $NOTIFICATION_URL"
      curl -s -X POST "$NOTIFICATION_URL/message?token=$NOTIFICATION_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":0}" >/dev/null
      if [ $? -eq 0 ]; then
        success "Gotify notification sent"
      else
        error "Failed to send Gotify notification"
      fi
      ;;
    *)
      warn "Unsupported notification service: $NOTIFICATION_SERVICE"
      ;;
  esac
}

updates_summary=""
updates_found=false

# Iterate only directories with config.json (add-ons)
for addon_dir in "$REPO_DIR"/*/; do
  addon_dir=${addon_dir%/}
  addon=$(basename "$addon_dir")

  # Skip hidden dirs
  if [[ "$addon" == .* ]]; then
    debug "Skipping hidden directory $addon"
    continue
  fi

  # Check config.json presence
  config_file="$addon_dir/config.json"
  if [ ! -f "$config_file" ]; then
    warn "Add-on $addon missing config.json, skipping."
    continue
  fi

  # Read current version
  current_version=$(extract_current_version "$addon_dir")

  # Read build.json if present (keep for later if needed)
  build_file="$addon_dir/build.json"
  updater_file="$addon_dir/updater.json"

  docker_image=$(jq -r '.image // empty' "$config_file")

  if [ -z "$docker_image" ]; then
    warn "Add-on $addon has no Docker image defined, skipping."
    continue
  fi

  docker_image="${docker_image//\{arch\}/amd64}"

  debug "Checking add-on: $addon"
  debug "Current version: $current_version"
  debug "Docker image: $docker_image"

  # Fetch available tags based on registry
  available_tags=""
  if [[ "$docker_image" =~ ^ghcr.io/ ]]; then
    repo_path="${docker_image#ghcr.io/}"
    repo_path="${repo_path%"-amd64"}"
    tags_url="https://ghcr.io/v2/$repo_path/tags/list"
    debug "Fetching tags from GHCR: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    if [ -z "$tags_json" ]; then
      warn "Failed to fetch tags from GHCR for $docker_image"
      continue
    fi
    available_tags=$(echo "$tags_json" | jq -r '.tags[]?' || echo "")

  elif [[ "$docker_image" =~ ^docker.io/ ]] || [[ ! "$docker_image" =~ / ]]; then
    if [[ "$docker_image" =~ ^docker.io/ ]]; then
      image_path="${docker_image#docker.io/}"
    else
      image_path="$docker_image"
    fi
    if [[ "$image_path" != */* ]]; then
      user_repo="library/$image_path"
    else
      user_repo="$image_path"
    fi
    tags_url="https://registry.hub.docker.com/v2/repositories/$user_repo/tags?page_size=100"
    debug "Fetching tags from Docker Hub: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    if [ -z "$tags_json" ]; then
      warn "Failed to fetch tags from Docker Hub for $docker_image"
      continue
    fi
    available_tags=$(echo "$tags_json" | jq -r '.results[].name' || echo "")

  elif [[ "$docker_image" =~ ^lscr.io/ ]]; then
    repo_path="${docker_image#lscr.io/}"
    repo_path="${repo_path%":*"}"
    tags_url="https://registry.hub.docker.com/v2/repositories/linuxserver/$repo_path/tags?page_size=100"
    debug "Fetching tags from LinuxServer.io: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    if [ -z "$tags_json" ]; then
      warn "Failed to fetch tags from LinuxServer.io for $docker_image"
      continue
    fi
    available_tags=$(echo "$tags_json" | jq -r '.results[].name' || echo "")

  else
    warn "Unsupported Docker registry for $docker_image. Skipping."
    continue
  fi

  # Normalize tags and exclude empty, latest, arch prefixes
  filtered_tags=$(echo "$available_tags" | while read -r tag; do normalize_tag "$tag"; done | grep -v '^$' | sort -Vr)

  if [ -z "$filtered_tags" ]; then
    warn "No valid version tags found for $docker_image"
    continue
  fi

  latest_version=$(echo "$filtered_tags" | head -n1)
  debug "Latest available version: $latest_version"

  update_needed=false
  if [ -z "$current_version" ]; then
    update_needed=true
  else
    if version_lt "$current_version" "$latest_version"; then
      update_needed=true
    fi
  fi

  if $update_needed; then
    info "Add-on $addon update available: $current_version -> $latest_version"
    if [ "$DRY_RUN" = false ]; then
      # Update version in config.json
      jq --arg ver "$latest_version" '.version=$ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

      # Update or create updater.json
      echo "{\"version\":\"$latest_version\"}" > "$updater_file"

      # Update changelog
      update_changelog "$addon_dir" "$latest_version"

      updates_summary+="\n✅ Updated $addon to version $latest_version"
      updates_found=true
    else
      updates_summary+="\n📝 Dry run: update available for $addon from $current_version to $latest_version"
      updates_found=true
    fi
  else
    info "Add-on $addon is up to date ($current_version)"
    updates_summary+="\nℹ️ $addon checked - no update needed"
  fi
done

# Commit and push if changes
if [ "$DRY_RUN" = false ] && [ "$updates_found" = true ]; then
  if [ "$SKIP_PUSH" = false ]; then
    git add .
    if git commit -m "chore: update add-on versions"; then
      git push
    else
      info "No changes to commit"
    fi
  else
    info "Skipping git push due to skip_push=true"
  fi
fi

# Send notification regardless of updates
if [ "$NOTIFICATIONS_ENABLED" = true ]; then
  notification_title="Add-on Update Summary"
  notification_message="Add-on Update Summary\n$updates_summary\nLast run: $(date)"

  if $updates_found && [ "$NOTIFY_ON_UPDATES" = true ]; then
    send_notification "$notification_title" "$notification_message"
  elif ! $updates_found && [ "$NOTIFY_ON_SUCCESS" = true ]; then
    send_notification "$notification_title" "$notification_message"
  fi
fi

success "Add-on update check complete."

# Keep running for cron style timing (or replace with actual cron schedule)
while true; do sleep 3600; done
