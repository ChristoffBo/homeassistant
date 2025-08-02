#!/bin/sh
set -e

# ======================
# CONFIGURATION
# ======================
CONFIG_FILE="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
NOTIFY_PAYLOAD_FILE="/tmp/notify_payload.json"

# Load config
load_config() {
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "Config file $CONFIG_FILE not found!"
    exit 1
  fi

  GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_FILE")
  GITEA_REPO=$(jq -r '.gitea_repo // empty' "$CONFIG_FILE")
  GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_FILE")
  GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_FILE")
  GITEA_USERNAME=$(jq -r '.gitea_username // empty' "$CONFIG_FILE")
  GITEA_TOKEN=$(jq -r '.gitea_token // empty' "$CONFIG_FILE")
  TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_FILE")
  DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_FILE")
  SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_FILE")
  DEBUG=$(jq -r '.debug // false' "$CONFIG_FILE")
  NOTIFICATIONS_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_FILE")
  NOTIFY_SERVICE=$(jq -r '.notification_service // empty' "$CONFIG_FILE")
  NOTIFY_URL=$(jq -r '.notification_url // empty' "$CONFIG_FILE")
  NOTIFY_TOKEN=$(jq -r '.notification_token // empty' "$CONFIG_FILE")
  NOTIFY_TO=$(jq -r '.notification_to // empty' "$CONFIG_FILE")
  NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_FILE")
  NOTIFY_ON_ERROR=$(jq -r '.notify_on_error // false' "$CONFIG_FILE")
  NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates // false' "$CONFIG_FILE")
  CHECK_CRON=$(jq -r '.check_cron // empty' "$CONFIG_FILE")
}

# ======================
# Logging & Colors
# ======================
COLOR_RESET='\033[0m'
COLOR_GREEN='\033[0;32m'
COLOR_RED='\033[0;31m'
COLOR_YELLOW='\033[1;33m'
COLOR_CYAN='\033[0;36m'
COLOR_INFO='\033[0;34m'

log() {
  local type="$1"
  local msg="$2"
  local timestamp
  timestamp=$(date +"[%Y-%m-%d %H:%M:%S %Z]")
  case "$type" in
    INFO) printf "%b %b%s%b\n" "$COLOR_INFO" "$timestamp" " ℹ️ $msg" "$COLOR_RESET" | tee -a "$LOG_FILE" ;;
    WARN) printf "%b %b%s%b\n" "$COLOR_YELLOW" "$timestamp" " ⚠️ $msg" "$COLOR_RESET" | tee -a "$LOG_FILE" ;;
    ERROR) printf "%b %b%s%b\n" "$COLOR_RED" "$timestamp" " ❌ $msg" "$COLOR_RESET" | tee -a "$LOG_FILE" ;;
    DEBUG)
      if [ "$DEBUG" = true ]; then
        printf "%b %b%s%b\n" "$COLOR_CYAN" "$timestamp" " 🐛 $msg" "$COLOR_RESET" | tee -a "$LOG_FILE"
      fi
      ;;
    SUCCESS) printf "%b %b%s%b\n" "$COLOR_GREEN" "$timestamp" " ✅ $msg" "$COLOR_RESET" | tee -a "$LOG_FILE" ;;
    *) printf "%b %b%s%b\n" "$COLOR_INFO" "$timestamp" " $msg" "$COLOR_RESET" | tee -a "$LOG_FILE" ;;
  esac
}

# ======================
# Git clone or pull repo
# ======================
clone_or_pull_repo() {
  if [ -n "$GITHUB_REPO" ]; then
    log INFO "Using GitHub repository and credentials"
    if [ ! -d "$REPO_DIR/.git" ]; then
      log INFO "Cloning GitHub repo: $GITHUB_REPO"
      if [ "$DRY_RUN" = true ]; then
        log INFO "Dry run enabled, skipping clone"
      else
        git clone "$GITHUB_REPO" "$REPO_DIR"
      fi
    else
      log INFO "Repository exists. Pulling latest changes..."
      if [ "$DRY_RUN" = true ]; then
        log INFO "Dry run enabled, skipping pull"
      else
        cd "$REPO_DIR"
        git pull origin main
      fi
    fi
  elif [ -n "$GITEA_REPO" ]; then
    log INFO "Using Gitea repository and credentials"
    if [ ! -d "$REPO_DIR/.git" ]; then
      log INFO "Cloning Gitea repo: $GITEA_REPO"
      if [ "$DRY_RUN" = true ]; then
        log INFO "Dry run enabled, skipping clone"
      else
        git clone "$GITEA_REPO" "$REPO_DIR"
      fi
    else
      log INFO "Repository exists. Pulling latest changes..."
      if [ "$DRY_RUN" = true ]; then
        log INFO "Dry run enabled, skipping pull"
      else
        cd "$REPO_DIR"
        git pull origin main
      fi
    fi
  else
    log ERROR "No GitHub or Gitea repository URL configured."
    exit 1
  fi
}

# ======================
# Normalize Docker tag versions (strip arch prefixes, handle 'v' prefixes)
# ======================
normalize_version() {
  local version="$1"
  # Strip architecture prefixes like amd64-, armhf-
  version="${version##amd64-}"
  version="${version##armhf-}"
  version="${version##arm64-}"
  version="${version##i386-}"
  version="${version##x86_64-}"

  # Strip leading 'v'
  version="${version#v}"

  echo "$version"
}

# ======================
# Fetch Docker tags based on image registry
# ======================
fetch_docker_tags() {
  local image="$1"
  local tags_url=""
  local tags_json=""
  local repo=""
  local page=1
  local tags_list=""
  local registry=""

  # Identify registry and repo path
  if echo "$image" | grep -q '^ghcr.io/'; then
    # GitHub Container Registry
    registry="ghcr"
    # Remove registry prefix and possible arch suffix for repo
    repo=$(echo "$image" | sed -E 's#^ghcr.io/([^:/]+/[^:/]+)(:[^:]*)?$#\1#' | sed 's/-amd64$//')
    tags_url="https://ghcr.io/v2/$repo/tags/list"
  elif echo "$image" | grep -q '^lscr.io/'; then
    # LinuxServer.io Registry
    registry="lscr"
    repo=$(echo "$image" | sed -E 's#^lscr.io/([^:/]+)(:[^:]*)?$#\1#')
    tags_url="https://lscr.io/v2/$repo/tags/list"
  elif echo "$image" | grep -q '/'; then
    # DockerHub
    registry="dockerhub"
    repo=$(echo "$image" | cut -d ':' -f1)
    # DockerHub v2 API, note repo may need org/user
    tags_url="https://registry.hub.docker.com/v2/repositories/$repo/tags/?page_size=100"
  else
    # Unknown registry
    registry="unknown"
  fi

  if [ "$registry" = "unknown" ]; then
    log WARN "Unsupported Docker registry for $image. Skipping tag fetch."
    echo ""
    return
  fi

  if [ "$DEBUG" = true ]; then
    log DEBUG "Fetching tags from $registry: $tags_url"
  fi

  # Fetch tags JSON (retry 3 times)
  local attempt=0
  while [ $attempt -lt 3 ]; do
    tags_json=$(curl -sSL --retry 3 "$tags_url" || echo "")
    if [ -n "$tags_json" ]; then
      break
    fi
    attempt=$((attempt+1))
    sleep 1
  done

  if [ -z "$tags_json" ]; then
    log WARN "Could not retrieve tags for $image"
    echo ""
    return
  fi

  # Parse tags based on registry JSON format
  case "$registry" in
    ghcr)
      # GHCR tags under .tags[].name
      tags_list=$(echo "$tags_json" | jq -r '.tags[].name' 2>/dev/null || echo "")
      ;;
    lscr)
      # LinuxServer tags under .tags[].name
      tags_list=$(echo "$tags_json" | jq -r '.tags[].name' 2>/dev/null || echo "")
      ;;
    dockerhub)
      # DockerHub tags under .results[].name
      tags_list=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null || echo "")
      ;;
  esac

  echo "$tags_list"
}

# ======================
# Compare semantic versions
# Returns 0 if v1 < v2, 1 otherwise
# ======================
version_lt() {
  # Use sort -V for version comparison, output ascending sorted list of 2 versions, pick first
  if [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" != "$2" ]; then
    return 0
  else
    return 1
  fi
}

# ======================
# Update add-on metadata files and changelog
# ======================
update_addon_files() {
  local addon_dir="$1"
  local new_version="$2"

  # Files: config.json, build.json, updater.json, CHANGELOG.md
  local config_json="$addon_dir/config.json"
  local build_json="$addon_dir/build.json"
  local updater_json="$addon_dir/updater.json"
  local changelog_md="$addon_dir/CHANGELOG.md"

  # Update config.json 'version' field if exists
  if [ -f "$config_json" ]; then
    if [ "$DRY_RUN" = false ]; then
      jq --arg ver "$new_version" '.version=$ver' "$config_json" > "${config_json}.tmp" && mv "${config_json}.tmp" "$config_json"
    fi
  fi

  # Update build.json 'version' field if exists
  if [ -f "$build_json" ]; then
    if [ "$DRY_RUN" = false ]; then
      jq --arg ver "$new_version" '.version=$ver' "$build_json" > "${build_json}.tmp" && mv "${build_json}.tmp" "$build_json"
    fi
  fi

  # Update updater.json 'last_version' field if exists
  if [ -f "$updater_json" ]; then
    if [ "$DRY_RUN" = false ]; then
      jq --arg ver "$new_version" '.last_version=$ver' "$updater_json" > "${updater_json}.tmp" && mv "${updater_json}.tmp" "$updater_json"
    fi
  fi

  # Append changelog entry with date
  if [ "$DRY_RUN" = false ]; then
    local date_str
    date_str=$(date +"%Y-%m-%d")
    echo "## $new_version - $date_str" >> "$changelog_md"
  fi
}

# ======================
# Send notification via Gotify, Apprise, Mailrise
# ======================
send_notification() {
  local title="$1"
  local message="$2"

  if [ "$NOTIFICATIONS_ENABLED" != true ]; then
    log INFO "Notifications disabled, skipping send."
    return
  fi

  case "$NOTIFY_SERVICE" in
    gotify)
      if [ -z "$NOTIFY_URL" ] || [ -z "$NOTIFY_TOKEN" ]; then
        log WARN "Gotify URL or token not configured."
        return
      fi
      local payload
      payload=$(jq -n --arg title "$title" --arg message "$message" \
        '{title: $title, message: $message, priority: 5}')
      if [ "$DRY_RUN" = false ]; then
        curl -s -X POST "$NOTIFY_URL/message?token=$NOTIFY_TOKEN" -H "Content-Type: application/json" -d "$payload" >/dev/null 2>&1
        log INFO "Gotify notification sent"
      else
        log INFO "Dry run enabled, skipping notification send"
      fi
      ;;
    apprise)
      if [ -z "$NOTIFY_URL" ]; then
        log WARN "Apprise URL not configured."
        return
      fi
      if [ "$DRY_RUN" = false ]; then
        curl -s -X POST "$NOTIFY_URL" -d "body=$message&title=$title" >/dev/null 2>&1
        log INFO "Apprise notification sent"
      else
        log INFO "Dry run enabled, skipping notification send"
      fi
      ;;
    mailrise)
      if [ -z "$NOTIFY_URL" ]; then
        log WARN "Mailrise URL not configured."
        return
      fi
      if [ "$DRY_RUN" = false ]; then
        curl -s -X POST "$NOTIFY_URL" -d "message=$message" >/dev/null 2>&1
        log INFO "Mailrise notification sent"
      else
        log INFO "Dry run enabled, skipping notification send"
      fi
      ;;
    *)
      log WARN "Unknown notification service: $NOTIFY_SERVICE"
      ;;
  esac
}

# ======================
# Main execution
# ======================
main() {
  load_config
  log INFO "🔁 Home Assistant Add-on Updater Starting"
  log INFO "========= CONFIGURATION =========="
  log INFO "GitHub Repo: $GITHUB_REPO"
  log INFO "Gitea Repo: $GITEA_REPO"
  log INFO "Dry Run: $DRY_RUN"
  log INFO "Skip Push: $SKIP_PUSH"
  log INFO "Timezone: $TIMEZONE"
  log INFO "Debug Mode: $DEBUG"
  log INFO "Notifications Enabled: $NOTIFICATIONS_ENABLED"
  log INFO "Notification Service: $NOTIFY_SERVICE"
  log INFO "Notify on Success: $NOTIFY_ON_SUCCESS"
  log INFO "Notify on Error: $NOTIFY_ON_ERROR"
  log INFO "Notify on Updates: $NOTIFY_ON_UPDATES"
  log INFO "=================================="

  clone_or_pull_repo || {
    log ERROR "Git operation failed"
    [ "$NOTIFY_ON_ERROR" = true ] && send_notification "Add-on Updater Error" "Git operation failed"
    exit 1
  }

  # Start checking add-ons
  cd "$REPO_DIR"

  # Collect addons dirs (any directory with config.json inside)
  ADDONS_DIRS=$(find . -maxdepth 1 -type d ! -name '.' | while read -r d; do
    if [ -f "$d/config.json" ]; then
      echo "$d"
    fi
  done)

  if [ -z "$ADDONS_DIRS" ]; then
    log ERROR "No add-ons found in repo at $REPO_DIR"
    [ "$NOTIFY_ON_ERROR" = true ] && send_notification "Add-on Updater Error" "No add-ons found in repo"
    exit 1
  fi

  local updates_found=false
  local summary=""

  for addon in $ADDONS_DIRS; do
    local addon_name
    addon_name=$(basename "$addon")
    log INFO "Checking add-on: $addon_name"

    local config_json="$addon/config.json"
    local build_json="$addon/build.json"
    local updater_json="$addon/updater.json"

    if [ ! -f "$config_json" ]; then
      log WARN "Add-on $addon_name missing config.json, skipping."
      continue
    fi

    # Read current version and docker image
    local current_version
    current_version=$(jq -r '.version //
