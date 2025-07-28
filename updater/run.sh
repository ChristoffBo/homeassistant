#!/usr/bin/env bash
set -euo pipefail

# =============================================
#  Configuration
# =============================================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
TEMP_FILE="/tmp/updater.tmp"

# Colors for logging
COLOR_RESET="\033[0m"
COLOR_RED="\033[0;31m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[0;33m"
COLOR_BLUE="\033[0;34m"
COLOR_CYAN="\033[0;36m"

# =============================================
#  Functions
# =============================================

# Initialize logging
init_logging() {
  mkdir -p "$(dirname "$LOG_FILE")"
  touch "$LOG_FILE"
  exec > >(tee -a "$LOG_FILE")
  exec 2>&1
}

log() {
  local color="$1"
  shift
  echo -e "$(date '+%Y-%m-%d %H:%M:%S') ${color}$*${COLOR_RESET}"
}

# Check for required dependencies
check_dependencies() {
  local missing=()
  for cmd in jq git curl; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done
  
  if [ ${#missing[@]} -gt 0 ]; then
    log "$COLOR_RED" "Missing dependencies: ${missing[*]}"
    exit 1
  fi
}

# Load and validate configuration
load_config() {
  if [ ! -f "$CONFIG_PATH" ]; then
    log "$COLOR_RED" "Config file not found: $CONFIG_PATH"
    exit 1
  fi

  # Required configuration
  GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
  GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
  
  [ -z "$GITHUB_REPO" ] && { log "$COLOR_RED" "github_repo not set"; exit 1; }
  [ -z "$GITHUB_TOKEN" ] && { log "$COLOR_RED" "github_token not set"; exit 1; }

  # Optional configuration with defaults
  DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
  SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
  CHECK_CRON=$(jq -r '.check_cron // "0 3 * * *"' "$CONFIG_PATH")
  PERSISTENT=$(jq -r '.persistent // false' "$CONFIG_PATH")
  TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

  # Set timezone
  export TZ="$TIMEZONE"
}

# Setup authenticated Git URL
setup_git_auth() {
  if [[ "$GITHUB_REPO" == git@* ]]; then
    GIT_AUTH_REPO="$GITHUB_REPO"
  elif [[ "$GITHUB_REPO" == http* ]]; then
    GIT_AUTH_REPO="${GITHUB_REPO/https:\/\//https://${GITHUB_TOKEN}@}"
  else
    log "$COLOR_RED" "Unsupported GitHub URL format"
    exit 1
  fi
}

# Clone or update repository
manage_repo() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_BLUE" "Cloning repository..."
    git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" || {
      log "$COLOR_RED" "Failed to clone repository"
      exit 1
    }
  else
    log "$COLOR_BLUE" "Updating repository..."
    cd "$REPO_DIR"
    git remote set-url origin "$GIT_AUTH_REPO"
    git reset --hard HEAD
    git clean -fd
    git pull origin main || {
      log "$COLOR_RED" "Failed to pull updates"
      exit 1
    }
  fi
}

# Get latest Docker image tag
get_latest_tag() {
  local image="$1"
  log "$COLOR_CYAN" "Checking latest tag for $image"
  
  # Remove docker.io prefix if present
  local repo="${image#docker.io/}"
  repo="${repo%%:*}"

  local url="https://registry.hub.docker.com/v2/repositories/${repo}/tags/"
  local tag=$(curl -s "$url" | jq -r '.results[] | select(.name | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) | .name' | sort -Vr | head -n1)
  
  echo "${tag:-latest}"
}

# Main update check
check_updates() {
  local updates=0
  cd "$REPO_DIR"

  for addon in */; do
    addon="${addon%/}"
    [ "$addon" = "updater" ] && continue

    log "$COLOR_BLUE" "Checking $addon..."
    
    local config="$addon/config.json"
    [ ! -f "$config" ] && continue

    local current_version=$(jq -r '.version // "latest"' "$config")
    local image=$(jq -r '.image // empty' "$config")
    [ -z "$image" ] && continue

    local latest_version=$(get_latest_tag "$image")
    if [ "$latest_version" != "$current_version" ]; then
      log "$COLOR_GREEN" "Update available: $current_version → $latest_version"
      ((updates++))
      
      if [ "$DRY_RUN" != "true" ]; then
        jq --arg v "$latest_version" '.version = $v' "$config" > "$TEMP_FILE" && 
        mv "$TEMP_FILE" "$config" &&
        log "$COLOR_GREEN" "Updated $addon to $latest_version"
      fi
    else
      log "$COLOR_CYAN" "Already up-to-date"
    fi
  done

  return $updates
}

# Commit and push changes
commit_changes() {
  cd "$REPO_DIR"
  git add .
  
  if git commit -m "Update addon versions"; then
    log "$COLOR_GREEN" "Changes committed"
    [ "$SKIP_PUSH" = "true" ] || git push origin main
  else
    log "$COLOR_YELLOW" "No changes to commit"
  fi
}

# Setup cron job
setup_cron() {
  echo "$CHECK_CRON /run.sh" > /etc/crontabs/root
  crond -f -L /dev/stdout &
}

# =============================================
#  Main Execution
# =============================================
main() {
  # Initialize
  init_logging
  check_dependencies
  load_config
  setup_git_auth

  # Create lock file
  touch "$LOCK_FILE"
  trap 'rm -f "$LOCK_FILE" "$TEMP_FILE"' EXIT

  # Repository management
  manage_repo

  # Check for updates
  if check_updates; then
    [ "$DRY_RUN" = "true" ] || commit_changes
  fi

  # Persistent mode
  if [ "$PERSISTENT" = "true" ]; then
    log "$COLOR_BLUE" "Entering persistent mode..."
    [ -n "$CHECK_CRON" ] && setup_cron
    while true; do sleep 3600; done
  fi
}

# Prevent concurrent execution
[ -f "$LOCK_FILE" ] && { log "$COLOR_RED" "Script already running"; exit 1; }

main