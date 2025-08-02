#!/usr/bin/env bash
set -eo pipefail

# ======================
# ENVIRONMENT FIX
# ======================
if [ -z "$HOME" ]; then
  export HOME=/root
fi

# ======================
# CONFIGURATION PATHS
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
MAX_LOG_LINES=1000

# ======================
# COLORS FOR LOGGING
# ======================
COLOR_RESET="\033[0m"
COLOR_RED="\033[0;31m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[1;33m"
COLOR_CYAN="\033[0;36m"

# ======================
# UTILS: LOGGING
# ======================
log() {
  local type="$1"
  local msg="$2"
  local color="$COLOR_RESET"
  local prefix="ℹ️"

  case "$type" in
    info) prefix="ℹ️" ; color="$COLOR_CYAN" ;;
    success) prefix="✅" ; color="$COLOR_GREEN" ;;
    warn) prefix="⚠️" ; color="$COLOR_YELLOW" ;;
    error) prefix="❌" ; color="$COLOR_RED" ;;
    debug) prefix="🐛" ; color="$COLOR_YELLOW" ;;
  esac

  local timestamp
  timestamp=$(date +"[%Y-%m-%d %H:%M:%S %Z]")
  echo -e "${timestamp} ${color}${prefix} ${msg}${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# ======================
# READ CONFIG OPTIONS
# ======================
jq -e . >/dev/null 2>&1 <"$CONFIG_PATH" || {
  log error "Invalid or missing options.json"
  exit 1
}

github_repo=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
github_username=$(jq -r '.github_username // empty' "$CONFIG_PATH")
github_token=$(jq -r '.github_token // empty' "$CONFIG_PATH")

gitea_repo=$(jq -r '.gitea_repo // empty' "$CONFIG_PATH")
gitea_username=$(jq -r '.gitea_username // empty' "$CONFIG_PATH")
gitea_token=$(jq -r '.gitea_token // empty' "$CONFIG_PATH")

timezone=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
dry_run=$(jq -r '.dry_run // false' "$CONFIG_PATH")
skip_push=$(jq -r '.skip_push // false' "$CONFIG_PATH")
debug=$(jq -r '.debug // false' "$CONFIG_PATH")

notifications_enabled=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
notification_service=$(jq -r '.notification_service // empty' "$CONFIG_PATH")
notification_url=$(jq -r '.notification_url // empty' "$CONFIG_PATH")
notification_token=$(jq -r '.notification_token // empty' "$CONFIG_PATH")
notification_to=$(jq -r '.notification_to // empty' "$CONFIG_PATH")
notify_on_success=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
notify_on_error=$(jq -r '.notify_on_error // false' "$CONFIG_PATH")
notify_on_updates=$(jq -r '.notify_on_updates // false' "$CONFIG_PATH")

check_cron=$(jq -r '.check_cron // "0 10 * * *"' "$CONFIG_PATH")

# ======================
# DEBUG LOGGING FUNCTION
# ======================
debug_log() {
  if [ "$debug" = true ]; then
    log debug "$1"
  fi
}

# ======================
# SET TIMEZONE
# ======================
export TZ="$timezone"

# ======================
# HELPER: SEND NOTIFICATION
# ======================
send_notification() {
  local title="$1"
  local message="$2"
  local priority=0
  if [ "$notifications_enabled" != true ]; then
    debug_log "Notifications disabled, skipping notification."
    return 0
  fi

  if [ "$notification_service" = "gotify" ]; then
    local payload
    payload=$(jq -nc --arg title "$title" --arg message "$message" --argjson priority "$priority" \
      '{title: $title, message: $message, priority: $priority}')
    debug_log "Sending Gotify notification to $notification_url"
    curl -s -X POST "$notification_url/message?token=$notification_token" \
      -H "Content-Type: application/json" \
      -d "$payload" \
      >/dev/null 2>&1 && log success "Gotify notification sent" || log warn "Failed to send Gotify notification"
  else
    log warn "Notification service '$notification_service' is not supported."
  fi
}

# ======================
# GIT CLONE OR PULL
# ======================
clone_or_pull_repo() {
  local repo_url="$1"
  local username="$2"
  local token="$3"
  local dir="$4"

  if [ -d "$dir/.git" ]; then
    log info "Repository exists. Pulling latest changes..."
    cd "$dir"
    git config user.email "updater@example.com"
    git config user.name "Add-on Updater"
    if [ -n "$token" ] && [ -n "$username" ]; then
      local auth_repo_url
      auth_repo_url=$(echo "$repo_url" | sed -E "s#https://#https://${username}:${token}@#")
      git remote set-url origin "$auth_repo_url"
    fi
    git fetch --all --prune
    git reset --hard origin/main || git reset --hard origin/master
    cd - >/dev/null
  else
    log info "Cloning repository..."
    if [ -n "$token" ] && [ -n "$username" ]; then
      local auth_repo_url
      auth_repo_url=$(echo "$repo_url" | sed -E "s#https://#https://${username}:${token}@#")
      git clone "$auth_repo_url" "$dir"
    else
      git clone "$repo_url" "$dir"
    fi
    cd "$dir"
    git config user.email "updater@example.com"
    git config user.name "Add-on Updater"
    cd - >/dev/null
  fi
}

# ======================
# FETCH DOCKER TAGS
# ======================
fetch_docker_tags() {
  local image="$1"
  local tags_json
  local registry image_name

  if echo "$image" | grep -q '/'; then
    registry=$(echo "$image" | cut -d/ -f1)
    image_name=$(echo "$image" | cut -d/ -f2-)
  else
    registry="docker.io"
    image_name="$image"
  fi

  if [ "$registry" = "docker.io" ]; then
    tags_json=$(curl -s "https://hub.docker.com/v2/repositories/${image_name}/tags?page_size=100")
  else
    tags_json=""
  fi

  echo "$tags_json"
}

# ======================
# FILTER AND GET LATEST SEMVER TAG FROM TAG LIST
# ======================
get_latest_version_from_tags() {
  local tags_json="$1"
  local latest_version
  latest_version=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null \
    | grep -v -E 'latest|[0-9]{4}-[0-9]{2}-[0-9]{2}' \
    | grep -E '^v?[0-9]+\.[0-9]+(\.[0-9]+)?([-+].*)?$' \
    | sort -Vr | head -n1)
  echo "$latest_version"
}

# ======================
# VERSION COMPARE: Return 0 if v1 < v2, else 1
# ======================
version_lt() {
  [ "$1" = "$2" ] && return 1
  if [ "$(printf "%s\n%s\n" "$1" "$2" | sort -Vr | head -n1)" = "$2" ]; then
    return 0
  else
    return 1
  fi
}

# ======================
# UPDATE CONFIG.JSON VERSION
# ======================
update_version_in_config() {
  local file="$1"
  local new_version="$2"
  if [ "$dry_run" = true ]; then
    log info "[dry_run] Would update version in $file to $new_version"
  else
    jq --arg ver "$new_version" '.version = $ver' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
    log info "Updated version in $file to $new_version"
  fi
}

# ======================
# COMMIT AND PUSH CHANGES
# ======================
commit_and_push_changes() {
  cd "$REPO_DIR"
  git add -A
  if [ "$dry_run" = true ]; then
    log info "[dry_run] Would commit changes"
  else
    if git diff --cached --quiet; then
      log info "No changes to commit"
    else
      git commit -m "Update add-on versions [Automated]"
      if [ "$skip_push" = true ]; then
        log info "Skipping git push due to skip_push=true"
      else
        git push origin main
        log info "Pushed changes to remote"
      fi
    fi
  fi
  cd - >/dev/null
}

# ======================
# MAIN UPDATE CHECK LOGIC
# ======================
main() {
  log info "========== CONFIGURATION =========="
  log info "GitHub Repo: $github_repo"
  log info "Gitea Repo: $gitea_repo"
  log info "Dry Run: $dry_run"
  log info "Skip Push: $skip_push"
  log info "Timezone: $timezone"
  log info "Debug Mode: $debug"
  log info "Notifications Enabled: $notifications_enabled"
  log info "Notification Service: $notification_service"
  log info "Notify on Success: $notify_on_success"
  log info "Notify on Error: $notify_on_error"
  log info "Notify on Updates: $notify_on_updates"
  log info "==================================="

  local repo_url="$github_repo"
  local username="$github_username"
  local token="$github_token"
  if [ -n "$gitea_repo" ]; then
    repo_url="$gitea_repo"
    username="$gitea_username"
    token="$gitea_token"
    log info "Using Gitea repository and credentials"
  else
    log info "Using GitHub repository and credentials"
  fi

  clone_or_pull_repo "$repo_url" "$username" "$token" "$REPO_DIR"

  local updates_found=false
  local update_summary=""

  for addon_dir in "$REPO_DIR"/addons/*/; do
    [ -d "$addon_dir" ] || continue
    local addon_name
    addon_name=$(basename "$addon_dir")

    local config_file="$addon_dir/config.json"
    if [ ! -f "$config_file" ]; then
      debug_log "Skipping $addon_name: no config.json"
      continue
    fi

    local current_version
    current_version=$(jq -r '.version // empty' "$config_file")
    local docker_image
    docker_image=$(jq -r '.image // empty' "$config_file")
    if [ -z "$docker_image" ]; then
      debug_log "Skipping $addon_name: no docker image in config.json"
      continue
    fi

    log info "Checking add-on: $addon_name"
    log info "Current version: $current_version"
    log info "Docker image: $docker_image"

    local tags_json
    tags_json=$(fetch_docker_tags "$docker_image")

    if [ -z "$tags_json" ]; then
      log warn "Could not fetch tags for $docker_image"
      continue
    fi

    local available_version
    available_version=$(get_latest_version_from_tags "$tags_json")

    if [ -z "$available_version" ]; then
      available_version="latest"
    fi

    log info "Available version: $available_version"

    if [ "$available_version" = "latest" ] || [ "$current_version" = "latest" ]; then
      log info "$addon_name: Using 'latest' version tag, no update triggered."
    else
      if version_lt "$current_version" "$available_version"; then
        log success "$addon_name update available: $current_version -> $available_version"
        updates_found=true
        update_version_in_config "$config_file" "$available_version"
        update_summary="${update_summary}\n$addon_name: $current_version → $available_version"
      else
        log info "$addon_name already up to date"
      fi
    fi
  done

  commit_and_push_changes

  local notification_title="Add-on Update Summary"
  local notification_message
  if $updates_found; then
    notification_message="Updates found for add-ons:$update_summary"
    if [ "$notify_on_updates" = true ]; then
      send_notification "$notification_title" "$notification_message"
    fi
  else
    notification_message="No add-on updates found."
    if [ "$notify_on_success" = true ]; then
      send_notification "$notification_title" "$notification_message"
    fi
  fi

  log success "Add-on update check complete"
}

main
