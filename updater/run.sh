#!/usr/bin/env bash
set -euo pipefail

# Configuration paths
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
TEMP_FILE="/data/temp.json"

# Colors for logging
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# Initialize notification variables
NOTIFICATION_ENABLED=false
NOTIFICATION_SERVICE=""
NOTIFICATION_URL=""
NOTIFICATION_TOKEN=""
NOTIFICATION_TO=""
NOTIFY_ON_SUCCESS=false
NOTIFY_ON_ERROR=true
NOTIFY_ON_UPDATES=true

# Clear log file on startup
: > "$LOG_FILE"

# Logging function with timestamp
log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
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
    log "$COLOR_RED" "❌ Missing required dependencies: ${missing[*]}"
    log "$COLOR_YELLOW" "Please install them before running this script."
    exit 1
  fi
}

# Validate JSON file exists and is valid
validate_json_file() {
  local file="$1"
  if [ ! -f "$file" ]; then
    log "$COLOR_RED" "❌ JSON file not found: $file"
    return 1
  fi
  
  if ! jq empty "$file" >/dev/null 2>&1; then
    log "$COLOR_RED" "❌ Invalid JSON in file: $file"
    return 1
  fi
  
  if [ ! -s "$file" ]; then
    log "$COLOR_YELLOW" "⚠️ Empty JSON file: $file"
    return 1
  fi
  
  return 0
}

# Safe jq wrapper with error handling
safe_jq() {
  local query="$1"
  local file="$2"
  
  if ! validate_json_file "$file"; then
    return 1
  fi
  
  if ! jq -e "$query" "$file" >/dev/null 2>&1; then
    log "$COLOR_YELLOW" "⚠️ jq query failed for '$query' in $file"
    return 1
  fi
  
  jq -r "$query" "$file"
}

# Validate GitHub URL format
validate_github_url() {
  local url="$1"
  if [[ "$url" =~ ^https://github.com/.*/.*$ ]] || 
     [[ "$url" =~ ^git@github.com:.*/.*$ ]] || 
     [[ "$url" =~ ^https://.*@github.com/.*/.*$ ]]; then
    return 0
  else
    log "$COLOR_RED" "❌ Invalid GitHub URL format: $url"
    log "$COLOR_YELLOW" "   Must be one of:"
    log "$COLOR_YELLOW" "   - https://github.com/owner/repo"
    log "$COLOR_YELLOW" "   - git@github.com:owner/repo"
    log "$COLOR_YELLOW" "   - https://username:token@github.com/owner/repo"
    return 1
  fi
}

# Send notification via Gotify
send_notification() {
  local title="$1"
  local message="$2"
  local priority="${3:-0}"
  
  if [ "$NOTIFICATION_ENABLED" != "true" ]; then
    log "$COLOR_BLUE" "🔕 Notifications are disabled"
    return 0
  fi

  if [ -z "$NOTIFICATION_SERVICE" ] || [ -z "$NOTIFICATION_URL" ] || [ -z "$NOTIFICATION_TOKEN" ]; then
    log "$COLOR_RED" "❌ Notification service not properly configured"
    return 1
  fi

  log "$COLOR_CYAN" "🔔 Attempting to send notification via $NOTIFICATION_SERVICE"
  
  case "$NOTIFICATION_SERVICE" in
    "gotify")
      local response
      response=$(curl -s -w "%{http_code}" -o "$TEMP_FILE" -X POST \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $NOTIFICATION_TOKEN" \
        -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
        "$NOTIFICATION_URL/message" 2>> "$LOG_FILE")
      
      if [ "$response" -eq 200 ]; then
        log "$COLOR_GREEN" "✅ Gotify notification sent successfully"
        return 0
      else
        log "$COLOR_RED" "❌ Gotify notification failed with HTTP $response"
        [ -f "$TEMP_FILE" ] && log "$COLOR_RED" "   Response: $(cat "$TEMP_FILE")"
        return 1
      fi
      ;;
      
    *)
      log "$COLOR_YELLOW" "⚠️ Unknown notification service: $NOTIFICATION_SERVICE"
      return 1
      ;;
  esac
}

# Clone or update repository
clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking GitHub repository for updates..."
  
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_CYAN" "📦 Cloning repository from $GITHUB_REPO..."
    
    if ! validate_github_url "$GITHUB_REPO"; then
      exit 1
    fi
    
    if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_TOKEN" ]; then
      log "$COLOR_RED" "❌ GitHub credentials not configured!"
      log "$COLOR_YELLOW" "   Please set github_username and github_token in your addon configuration"
      exit 1
    fi
    
    if ! git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"; then
      log "$COLOR_RED" "❌ Failed to clone repository"
      log "$COLOR_YELLOW" "   Check your GitHub credentials and repository URL"
      exit 1
    fi
    log "$COLOR_GREEN" "✅ Successfully cloned repository"
  else
    if ! cd "$REPO_DIR"; then
      log "$COLOR_RED" "❌ Failed to enter repository directory"
      exit 1
    fi
    
    log "$COLOR_CYAN" "🔄 Pulling latest changes from GitHub..."
    
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      log "$COLOR_RED" "❌ $REPO_DIR is not a git repository!"
      exit 1
    fi
    
    # Reset any local changes
    git reset --hard HEAD >> "$LOG_FILE" 2>&1
    git clean -fd >> "$LOG_FILE" 2>&1
    
    if ! git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_RED" "❌ Git pull failed"
      log "$COLOR_YELLOW" "   Check your GitHub credentials and network connection"
      exit 1
    fi
    log "$COLOR_GREEN" "✅ Successfully pulled latest changes"
  fi
}

# Get latest Docker tag with rate limiting protection
get_latest_docker_tag() {
  local image="$1"
  local retries=3
  local wait_time=5
  local version="latest"
  
  # Remove 'docker.io/' prefix if present
  local image_name="${image#docker.io/}"
  # Extract repository name (without tag)
  local repo_name="${image_name%%:*}"
  
  for ((i=1; i<=retries; i++)); do
    log "$COLOR_BLUE" "   Checking Docker Hub for $repo_name (attempt $i/$retries)"
    
    local api_response
    api_response=$(curl -s -f --max-time 30 \
      "https://registry.hub.docker.com/v2/repositories/${repo_name}/tags/" || true)
    
    if [ -n "$api_response" ]; then
      version=$(echo "$api_response" | 
               jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))) | .name' | 
               sort -Vr | head -n1)
      
      if [ -n "$version" ] && [[ "$version" =~ ^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
        version=${version#v}  # Remove 'v' prefix if present
        log "$COLOR_BLUE" "   Found version: $version"
        break
      fi
    fi
    
    if [ $i -lt $retries ]; then
      log "$COLOR_YELLOW" "   ⏳ Retrying in $wait_time seconds..."
      sleep $wait_time
    fi
  done

  if [ -z "$version" ] || [[ ! "$version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    log "$COLOR_YELLOW" "   ⚠️ Could not determine latest version, using 'latest'"
    version="latest"
  fi

  echo "$version"
}

# Update add-on if needed
update_addon_if_needed() {
  local addon_path="$1"
  local addon_name=$(basename "$addon_path")
  
  if [[ "$addon_name" == "updater" ]]; then
    log "$COLOR_BLUE" "🔧 Skipping updater addon (self)"
    return
  fi

  log "$COLOR_CYAN" "🔍 Checking add-on: $addon_name"

  local image=""
  local current_version="latest"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"

  # Check config.json first
  if [[ -f "$config_file" ]] && validate_json_file "$config_file"; then
    image=$(safe_jq '.image // empty' "$config_file")
    current_version=$(safe_jq '.version // "latest"' "$config_file")
  fi

  # Fall back to build.json if no image found
  if [[ -z "$image" && -f "$build_file" ]] && validate_json_file "$build_file"; then
    local arch=$(uname -m)
    [[ "$arch" == "x86_64" ]] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | if type=="string" then . else empty end' "$build_file" 2>/dev/null || true)
  fi

  if [[ -z "$image" ]]; then
    log "$COLOR_YELLOW" "⚠️ No Docker image found for $addon_name"
    return
  fi

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [[ -z "$latest_version" ]]; then
    log "$COLOR_YELLOW" "⚠️ Could not determine latest version for $image"
    return
  fi

  log "$COLOR_BLUE" "   Current version: $current_version"
  log "$COLOR_BLUE" "   Available version: $latest_version"

  if [[ "$latest_version" != "$current_version" ]] && [[ "$latest_version" != "latest" ]]; then
    log "$COLOR_GREEN" "⬆️ Update available: $current_version → $latest_version"
    
    if [[ "$DRY_RUN" == "true" ]]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - would update to $latest_version"
      log "$COLOR_CYAN" "   Version $latest_version is available (current: $current_version)"
      return
    fi

    # Update config.json if it exists
    if [[ -f "$config_file" ]] && validate_json_file "$config_file"; then
      if jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp"; then
        mv "$config_file.tmp" "$config_file"
        log "$COLOR_GREEN" "✅ Updated version in config.json"
      else
        log "$COLOR_RED" "❌ Failed to update config.json"
      fi
    fi

    # Update build.json if it exists
    if [[ -f "$build_file" ]] && validate_json_file "$build_file" && 
       jq -e '.version' "$build_file" >/dev/null 2>&1; then
      if jq --arg v "$latest_version" '.version = $v' "$build_file" > "$build_file.tmp"; then
        mv "$build_file.tmp" "$build_file"
        log "$COLOR_GREEN" "✅ Updated version in build.json"
      else
        log "$COLOR_RED" "❌ Failed to update build.json"
      fi
    fi

    if [[ "$NOTIFY_ON_UPDATES" == "true" ]]; then
      send_notification "Add-on Update Available" "$addon_name: $current_version → $latest_version" 0
    fi
  else
    log "$COLOR_GREEN" "✔️ Already up to date"
  fi
}

# Main update check function
perform_update_check() {
  local start_time=$(date +%s)
  log "$COLOR_PURPLE" "🚀 Starting update check"
  
  clone_or_update_repo

  if ! cd "$REPO_DIR"; then
    log "$COLOR_RED" "❌ Failed to enter repository directory"
    exit 1
  fi
  
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local addon_count=0
  local updated_count=0
  for addon_path in "$REPO_DIR"/*/; do
    if [ -d "$addon_path" ]; then
      update_addon_if_needed "$addon_path"
      ((addon_count++))
      if [[ "$(git status --porcelain "$addon_path")" ]]; then
        ((updated_count++))
      fi
    fi
  done

  if [ $addon_count -eq 0 ]; then
    log "$COLOR_RED" "❌ No add-ons found in repository!"
    exit 1
  fi

  if [ $updated_count -gt 0 ] && [ "$(git status --porcelain)" ]; then
    if [ "$DRY_RUN" == "true" ]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping git commit/push"
      return
    fi
    
    if [ "$SKIP_PUSH" == "true" ]; then
      log "$COLOR_CYAN" "⏸️ Skip push enabled - committing changes locally but not pushing"
      git add .
      git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1
    else
      git add .
      git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1
      if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "✅ Git push successful."
        if [ "$NOTIFY_ON_SUCCESS" == "true" ]; then
          send_notification "Add-on Updater Success" "Updated $updated_count add-on(s) and pushed changes" 0
        fi
      else
        log "$COLOR_RED" "❌ Git push failed."
        if [ "$NOTIFY_ON_ERROR" == "true" ]; then
          send_notification "Add-on Updater Error" "Failed to push changes for $updated_count add-on(s)" 5
        fi
      fi
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found"
    if [ "$NOTIFY_ON_SUCCESS" == "true" ]; then
      send_notification "Add-on Updater Complete" "No add-on updates were available" 0
    fi
  fi
  
  local duration=$(( $(date +%s) - start_time ))
  log "$COLOR_PURPLE" "🏁 Update check completed in ${duration} seconds"
}

# Check for lock file to prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
  log "$COLOR_RED" "⚠️ Another update process is already running. Exiting."
  exit 1
fi

# Create lock file
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE" "$TEMP_FILE" 2>/dev/null' EXIT

# Main execution
check_dependencies

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Validate and read configuration
if ! validate_json_file "$CONFIG_PATH"; then
  log "$COLOR_RED" "❌ Invalid configuration in $CONFIG_PATH"
  exit 1
fi

# Read configuration with defaults
GITHUB_REPO=$(safe_jq '.github_repo' "$CONFIG_PATH" || { log "$COLOR_RED" "❌ github_repo is required"; exit 1; })
GITHUB_USERNAME=$(safe_jq '.github_username // ""' "$CONFIG_PATH")
GITHUB_TOKEN=$(safe_jq '.github_token // ""' "$CONFIG_PATH")
CHECK_CRON=$(safe_jq '.check_cron // "0 */6 * * *"' "$CONFIG_PATH")
TIMEZONE=$(safe_jq '.timezone // "UTC"' "$CONFIG_PATH")
MAX_LOG_LINES=$(safe_jq '.max_log_lines // 1000' "$CONFIG_PATH")
DRY_RUN=$(safe_jq '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(safe_jq '.skip_push // false' "$CONFIG_PATH")

# Notification settings
NOTIFICATION_ENABLED=$(safe_jq '.notifications_enabled // false' "$CONFIG_PATH")
if [ "$NOTIFICATION_ENABLED" == "true" ]; then
  NOTIFICATION_SERVICE=$(safe_jq '.notification_service // ""' "$CONFIG_PATH")
  NOTIFICATION_URL=$(safe_jq '.notification_url // ""' "$CONFIG_PATH")
  NOTIFICATION_TOKEN=$(safe_jq '.notification_token // ""' "$CONFIG_PATH")
  NOTIFICATION_TO=$(safe_jq '.notification_to // ""' "$CONFIG_PATH")
  NOTIFY_ON_SUCCESS=$(safe_jq '.notify_on_success // false' "$CONFIG_PATH")
  NOTIFY_ON_ERROR=$(safe_jq '.notify_on_error // true' "$CONFIG_PATH")
  NOTIFY_ON_UPDATES=$(safe_jq '.notify_on_updates // true' "$CONFIG_PATH")
fi

# Set timezone
export TZ="${TIMEZONE:-UTC}"

# Rotate log file if it's too large
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt "$MAX_LOG_LINES" ]; then
  log "$COLOR_YELLOW" "📜 Log file too large, rotating..."
  tail -n "$MAX_LOG_LINES" "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

# Construct authenticated repo URL
GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#(https?://)#\1$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
log "$COLOR_GREEN" "⚙️ Configuration:"
log "$COLOR_GREEN" "   - GitHub Repo: $GITHUB_REPO"
log "$COLOR_GREEN" "   - Dry run: $DRY_RUN"
log "$COLOR_GREEN" "   - Skip push: $SKIP_PUSH"
log "$COLOR_GREEN" "   - Check cron: $CHECK_CRON"
log "$COLOR_GREEN" "   - Timezone: $TIMEZONE"
if [ "$NOTIFICATION_ENABLED" == "true" ]; then
  log "$COLOR_GREEN" "🔔 Notifications: Enabled (Service: $NOTIFICATION_SERVICE)"
else
  log "$COLOR_GREEN" "🔔 Notifications: Disabled"
fi

# First run on startup
perform_update_check

# Main loop (if running continuously)
log "$COLOR_GREEN" "⏳ Waiting for cron triggers..."
while true; do
  sleep 60
done