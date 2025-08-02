#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
MAX_LOG_LINES=1000

# ======================
# COLOR DEFINITIONS
# ======================
COLOR_RESET="\033[0m"
COLOR_RED="\033[0;31m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[1;33m"
COLOR_BLUE="\033[0;34m"
COLOR_CYAN="\033[0;36m"

# ======================
# LOGGING FUNCTIONS
# ======================
log() {
  local level="$1"
  local color="$2"
  local message="$3"
  local timestamp
  timestamp=$(date +"[%Y-%m-%d %H:%M:%S %Z]")
  echo -e "${timestamp} ${color}${level}${COLOR_RESET} ${message}"
}

info() {
  log "ℹ️" "$COLOR_BLUE" "$1"
}

success() {
  log "✅" "$COLOR_GREEN" "$1"
}

warn() {
  log "⚠️" "$COLOR_YELLOW" "$1"
}

error() {
  log "❌" "$COLOR_RED" "$1" >&2
}

debug() {
  if [ "$DEBUG" = true ]; then
    log "🐛" "$COLOR_CYAN" "$1"
  fi
}

# ======================
# LOAD CONFIGURATION
# ======================
if [ ! -f "$CONFIG_PATH" ]; then
  error "Configuration file $CONFIG_PATH not found!"
  exit 1
fi

# jq is required to parse JSON options
if ! command -v jq &>/dev/null; then
  error "jq command not found. Please install jq."
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
GITEA_REPO=$(jq -r '.gitea_repo // empty' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
GITEA_TOKEN=$(jq -r '.gitea_token // empty' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
NOTIFICATIONS_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
NOTIFICATION_SERVICE=$(jq -r '.notification_service // empty' "$CONFIG_PATH")
NOTIFICATION_URL=$(jq -r '.notification_url // empty' "$CONFIG_PATH")
NOTIFICATION_TOKEN=$(jq -r '.notification_token // empty' "$CONFIG_PATH")
NOTIFICATION_TO=$(jq -r '.notification_to // empty' "$CONFIG_PATH")
NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
NOTIFY_ON_ERROR=$(jq -r '.notify_on_error // false' "$CONFIG_PATH")
NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates // false' "$CONFIG_PATH")

# Set TZ for all date commands
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

# ======================
# HELPER FUNCTIONS
# ======================

# Function to send notifications
send_notification() {
  local title="$1"
  local message="$2"
  if [ "$NOTIFICATIONS_ENABLED" != true ]; then
    debug "Notifications disabled; skipping send."
    return 0
  fi

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
    apprise)
      # Add Apprise implementation here if needed
      ;;
    mailrise)
      # Add Mailrise implementation here if needed
      ;;
    *)
      warn "Unsupported notification service: $NOTIFICATION_SERVICE"
      ;;
  esac
}

# Compare semantic versions, returns 0 if $1 < $2, 1 otherwise
version_lt() {
  # Returns 0 if $1 < $2 else 1
  # Use sort -V for semantic versioning
  [ "$(printf '%s\n%s' "$1" "$2" | sort -V | head -n1)" != "$2" ]
}

# Normalize Docker tags: remove arch prefixes and ignore "latest"
normalize_tag() {
  local tag="$1"
  # Remove common arch prefixes, e.g. amd64-, armhf-, etc.
  tag="${tag#amd64-}"
  tag="${tag#armhf-}"
  tag="${tag#arm64-}"
  tag="${tag#aarch64-}"
  tag="${tag#x86_64-}"
  # Return empty if tag is "latest" or empty
  if [ "$tag" = "latest" ] || [ -z "$tag" ]; then
    echo ""
  else
    echo "$tag"
  fi
}

# Extract add-on version from config.json
extract_current_version() {
  local addon_dir="$1"
  jq -r '.version // empty' "$addon_dir/config.json" 2>/dev/null || echo ""
}

# Update changelog for add-on
update_changelog() {
  local addon_dir="$1"
  local new_version="$2"
  local changelog_file="$addon_dir/CHANGELOG.md"

  if [ ! -f "$changelog_file" ]; then
    echo "# Changelog" >"$changelog_file"
  fi

  # Add new version entry with date
  echo -e "\n## $new_version - $(date +"%Y-%m-%d")" >>"$changelog_file"
  echo "- Updated to version $new_version" >>"$changelog_file"
}

# ======================
# REPO PREP
# ======================
if [ ! -d "$REPO_DIR/.git" ]; then
  # Clone repo, prefer GitHub if set, else Gitea
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

cd "$REPO_DIR"

# Set git user/email for commits
git config user.name "$GITHUB_USERNAME"
git config user.email "$GITHUB_USERNAME@users.noreply.github.com"

# Pull latest changes
info "Pulling latest changes from repository..."
if ! git pull --rebase; then
  error "Git pull failed"
  [ "$NOTIFY_ON_ERROR" = true ] && send_notification "Add-on Updater Error" "Git pull failed"
  exit 1
fi
info "Git pull completed."

# ======================
# FIND ADDONS (top-level dirs)
# ======================
addons=$(find "$REPO_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \;)

if [ -z "$addons" ]; then
  warn "No add-ons found in repo directory."
fi

updates_summary=""
updates_found=false

for addon in $addons; do
  info "Checking add-on: $addon"

  addon_dir="$REPO_DIR/$addon"
  config_file="$addon_dir/config.json"
  build_file="$addon_dir/build.json"
  updater_file="$addon_dir/updater.json"

  if [ ! -f "$config_file" ]; then
    warn "Add-on $addon missing config.json, skipping."
    continue
  fi

  current_version=$(extract_current_version "$addon_dir")
  docker_image=$(jq -r '.image // empty' "$config_file")

  if [ -z "$docker_image" ]; then
    warn "Add-on $addon has no Docker image defined, skipping."
    continue
  fi

  # Handle architecture placeholder {arch} if present - replace with 'amd64' for now
  docker_image="${docker_image//\{arch\}/amd64}"

  debug "Current version: $current_version"
  debug "Docker image: $docker_image"

  # Detect registry and get available tags
  available_version=""

  if echo "$docker_image" | grep -q '^ghcr.io/'; then
    # GHCR API: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#listing-packages-in-a-registry
    repo_path="${docker_image#ghcr.io/}"
    repo_path="${repo_path%%:*}"
    # GitHub token needed for private repos; here assume public
    tags_url="https://ghcr.io/v2/$repo_path/tags/list"
    debug "Fetching tags from GHCR: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    # Extract tags
    available_tags=$(echo "$tags_json" | jq -r '.tags[]?' || echo "")
  elif echo "$docker_image" | grep -q '^docker.io/'; then
    # Docker Hub API
    image_path="${docker_image#docker.io/}"
    # For official images, e.g. "redis", there's no username, only repo
    # Separate user and repo
    if [[ "$image_path" == *"/"* ]]; then
      user_repo="$image_path"
    else
      user_repo="library/$image_path"
    fi
    tags_url="https://registry.hub.docker.com/v2/repositories/$user_repo/tags?page_size=100"
    debug "Fetching tags from Docker Hub: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    available_tags=$(echo "$tags_json" | jq -r '.results[].name' || echo "")
  elif echo "$docker_image" | grep -q '^lscr.io/'; then
    # LinuxServer.io tags
    repo_path="${docker_image#lscr.io/}"
    repo_path="${repo_path%%:*}"
    tags_url="https://registry.hub.docker.com/v2/repositories/linuxserver/$repo_path/tags?page_size=100"
    debug "Fetching tags from LinuxServer.io: $tags_url"
    tags_json=$(curl -s "$tags_url" || echo "")
    available_tags=$(echo "$tags_json" | jq -r '.results[].name' || echo "")
  else
    warn "Unsupported Docker registry for $docker_image. Skipping."
    continue
  fi

  if [ -z "$available_tags" ]; then
    warn "Could not retrieve tags for $docker_image"
    continue
  fi

  # Filter tags - ignore "latest" and empty, and remove arch prefixes
  filtered_tags=$(echo "$available_tags" | while read -r tag; do normalize_tag "$tag"; done | grep -v '^$' | sort -Vr)

  if [ -z "$filtered_tags" ]; then
    warn "No valid version tags found for $docker_image"
    continue
  fi

  # Take the highest semantic version tag available
  latest_version=$(echo "$filtered_tags" | head -n1)

  debug "Latest available version: $latest_version"

  # If current version is empty, treat as update needed
  update_needed=false
  if [ -z "$current_version" ]; then
    update_needed=true
  else
    # Compare versions, update if latest_version > current_version
    if version_lt "$current_version" "$latest_version"; then
      update_needed=true
    fi
  fi

  if $update_needed; then
    info "Add-on $addon update available: $current_version -> $latest_version"
    if [ "$DRY_RUN" = false ]; then
      # Update config.json version
      jq --arg ver "$latest_version" '.version=$ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

      # Update updater.json
      echo "{\"version\":\"$latest_version\"}" >"$updater_file"

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

if [ "$DRY_RUN" = false ] && [ "$updates_found" = true ]; then
  if [ "$SKIP_PUSH" = false ]; then
    git add .
    git commit -m "chore: update add-on versions" || info "No changes to commit"
    git push || error "Git push failed"
  else
    info "Skipping git push due to skip_push=true"
  fi
fi

# Send notification always with summary
if [ "$NOTIFICATIONS_ENABLED" = true ]; then
  notification_title="Add-on Update Summary"
  notification_message="Add-on Update Summary\n$updates_summary\nLast run: $(date)"

  # Determine if notification should be sent based on updates and config
  if $updates_found && [ "$NOTIFY_ON_UPDATES" = true ]; then
    send_notification "$notification_title" "$notification_message"
  elif ! $updates_found && [ "$NOTIFY_ON_SUCCESS" = true ]; then
    send_notification "$notification_title" "$notification_message"
  fi
fi

success "Add-on update check complete."

# Sleep forever to satisfy cron-based scheduling
while true; do sleep 3600; done
