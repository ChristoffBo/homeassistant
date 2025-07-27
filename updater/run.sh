#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# Clear log file on startup
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Check for lock file to prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
  log "$COLOR_RED" "⚠️ Another update process is already running. Exiting."
  exit 1
fi

# Create lock file
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Read configuration
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron // "0 */6 * * *"' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
MAX_LOG_LINES=$(jq -r '.max_log_lines // 1000' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")

# Set timezone
export TZ="$TIMEZONE"

# Rotate log file if it's too large
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt "$MAX_LOG_LINES" ]; then
  log "$COLOR_YELLOW" "📜 Log file too large, rotating..."
  tail -n "$MAX_LOG_LINES" "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#(https?://)#\1$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Cloning repository..."
    if git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      exit 1
    fi
  else
    cd "$REPO_DIR"
    log "$COLOR_PURPLE" "🔄 Pulling latest changes from GitHub..."
    
    # Reset any local changes that might conflict
    git reset --hard HEAD >> "$LOG_FILE" 2>&1
    git clean -fd >> "$LOG_FILE" 2>&1
    
    if ! git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_RED" "❌ Initial git pull failed. Attempting recovery..."
      
      # Check for specific git issues
      if [ -d ".git/rebase-merge" ] || [ -d ".git/rebase-apply" ]; then
        log "$COLOR_YELLOW" "⚠️ Detected unfinished rebase, aborting it..."
        git rebase --abort >> "$LOG_FILE" 2>&1 || true
      fi
      
      # Reset to origin/main
      git fetch origin main >> "$LOG_FILE" 2>&1
      git reset --hard origin/main >> "$LOG_FILE" 2>&1
      
      if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "✅ Git pull successful after recovery."
      else
        log "$COLOR_RED" "❌ Git pull still failed after recovery. Last 20 log lines:"
        tail -n 20 "$LOG_FILE" | sed 's/^/    /'
        exit 1
      fi
    else
      log "$COLOR_GREEN" "✅ Git pull successful."
    fi
  fi
}

get_docker_last_updated_date() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  
  if [[ "$image_name" =~ ^ghcr.io/ ]]; then
    # For GitHub Container Registry
    local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
    local package=$(echo "$image_name" | cut -d/ -f4)
    local token=$(curl -s "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token')
    if [ -n "$token" ]; then
      local manifest=$(curl -s -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
        "https://ghcr.io/v2/$org_repo/$package/manifests/latest")
      if [ -n "$manifest" ]; then
        local last_updated=$(echo "$manifest" | jq -r '.config.lastUpdated' 2>/dev/null)
        if [ -n "$last_updated" ] && [ "$last_updated" != "null" ]; then
          date -d "$last_updated" '+%d-%m-%Y'
          return
        fi
      fi
    fi
  else
    # For Docker Hub
    local namespace=$(echo "$image_name" | cut -d/ -f1)
    local repo=$(echo "$image_name" | cut -d/ -f2)
    if [ "$namespace" = "$repo" ]; then
      # Official image (library/)
      local api_response=$(curl -s "https://hub.docker.com/v2/repositories/library/$repo/tags/latest")
    else
      # User/org image
      local api_response=$(curl -s "https://hub.docker.com/v2/repositories/$namespace/$repo/tags/latest")
    fi
    
    if [ -n "$api_response" ]; then
      local last_updated=$(echo "$api_response" | jq -r '.last_updated' 2>/dev/null)
      if [ -n "$last_updated" ] && [ "$last_updated" != "null" ]; then
        date -d "$last_updated" '+%d-%m-%Y'
        return
      fi
    fi
  fi
  
  # Fallback to current date if we couldn't get the last updated date
  date '+%d-%m-%Y'
}

get_latest_docker_tag() {
  local image="$1"
  local log_prefix="$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${COLOR_CYAN}🔍 Checking latest version for $image${COLOR_RESET}"
  echo "$log_prefix" >> "$LOG_FILE"
  
  # Remove :latest or other tags if present
  local image_name=$(echo "$image" | cut -d: -f1)
  local latest_version=""
  
  # Try different methods based on image source
  if [[ "$image_name" =~ ^linuxserver/ ]] || [[ "$image_name" =~ ^lscr.io/linuxserver/ ]]; then
    # For linuxserver.io images
    local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
    local api_response=$(curl -s "https://api.linuxserver.io/v1/images/$lsio_name/tags")
    if [ -n "$api_response" ]; then
      latest_version=$(echo "$api_response" | 
                      jq -r '.tags[] | select(.name != "latest") | .name' | 
                      grep -E '^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$' | 
                      sort -Vr | head -n1)
    fi
  elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
    # For GitHub Container Registry
    local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
    local package=$(echo "$image_name" | cut -d/ -f4)
    local token=$(curl -s "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token')
    if [ -n "$token" ]; then
      latest_version=$(curl -s -H "Authorization: Bearer $token" \
                         "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
                         jq -r '.tags[] | select(. != "latest" and (. | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$")))' | \
                         sort -Vr | head -n1)
    fi
  else
    # For standard Docker Hub images
    local namespace=$(echo "$image_name" | cut -d/ -f1)
    local repo=$(echo "$image_name" | cut -d/ -f2)
    if [ "$namespace" = "$repo" ]; then
      # Official image (library/)
      local api_response=$(curl -s "https://registry.hub.docker.com/v2/repositories/library/$repo/tags/")
      if [ -n "$api_response" ]; then
        latest_version=$(echo "$api_response" | 
                        jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                        sort -Vr | head -n1)
      fi
    else
      # User/org image
      local api_response=$(curl -s "https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/")
      if [ -n "$api_response" ]; then
        latest_version=$(echo "$api_response" | 
                        jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                        sort -Vr | head -n1)
      fi
    fi
  fi

  # If we couldn't determine version, use the last updated date of the 'latest' tag
  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    local last_updated_date=$(get_docker_last_updated_date "$image")
    echo "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${COLOR_YELLOW}⚠️ Using last updated date ($last_updated_date) for $image${COLOR_RESET}" >> "$LOG_FILE"
    echo "$last_updated_date"
  else
    echo "$latest_version"
  fi
}

# ... [rest of the script remains the same] ...