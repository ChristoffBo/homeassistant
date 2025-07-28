#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

# Color definitions
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# Notification setup
NOTIFICATION_ENABLED=false
NOTIFICATION_SERVICE=""
NOTIFICATION_URL=""
NOTIFICATION_TOKEN=""
NOTIFICATION_TO=""
NOTIFY_ON_SUCCESS=false
NOTIFY_ON_ERROR=true
NOTIFY_ON_UPDATES=true

# Initialize logging
mkdir -p "$(dirname "$LOG_FILE")"
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

sanitize_version() {
  echo "$1" | sed -e 's/\x1b\[[0-9;]*m//g' -e 's/[^a-zA-Z0-9._-]//g'
}

validate_version_tag() {
  local version=$(sanitize_version "$1")
  [[ "$version" =~ ^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$ ]] || \
  [[ "$version" == "latest" ]]
}

safe_jq() {
  local file="$1"
  local query="$2"
  local default="$3"
  
  if [[ ! -f "$file" ]]; then
    echo "$default"
    return
  fi
  
  local result=$(jq -r "$query" "$file" 2>/dev/null || echo "$default")
  if [[ "$result" == "null" ]]; then
    echo "$default"
  else
    echo "$result"
  fi
}

verify_config_version() {
  local config_file="$1"
  local max_attempts=3
  local attempt=0
  
  while [[ $attempt -lt $max_attempts ]]; do
    if [[ ! -f "$config_file" ]]; then
      return 1
    fi
    
    local current_version=$(safe_jq "$config_file" '.version' "latest")
    current_version=$(sanitize_version "$current_version")
    
    if validate_version_tag "$current_version"; then
      return 0
    else
      log "$COLOR_YELLOW" "⚠️ Invalid version in $config_file, attempt $((attempt+1))/$max_attempts"
      attempt=$((attempt+1))
      sleep 1
    fi
  done
  
  log "$COLOR_RED" "❌ Failed to validate version in $config_file after $max_attempts attempts"
  return 1
}

write_safe_version() {
  local file="$1"
  local version="$2"
  local max_attempts=3
  local attempt=0
  local temp_file="${file}.tmp"
  
  version=$(sanitize_version "$version")
  
  while [[ $attempt -lt $max_attempts ]]; do
    if [[ ! -f "$file" ]]; then
      log "$COLOR_RED" "❌ Config file $file does not exist"
      return 1
    fi
    
    if jq --arg v "$version" '.version = $v' "$file" > "$temp_file" 2>/dev/null; then
      if verify_config_version "$temp_file"; then
        mv "$temp_file" "$file"
        return 0
      fi
    fi
    
    attempt=$((attempt+1))
    log "$COLOR_YELLOW" "⚠️ Version write attempt $attempt/$max_attempts failed for $file"
    sleep 1
  done
  
  log "$COLOR_RED" "❌ Failed to write version to $file after $max_attempts attempts"
  return 1
}

get_latest_docker_tag() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  local latest_version=""
  local retries=3
  
  for ((i=1; i<=retries; i++)); do
    if [[ "$image_name" =~ ^linuxserver/ ]] || [[ "$image_name" =~ ^lscr.io/linuxserver/ ]]; then
      local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
      local api_response=$(curl -sS --fail "https://api.linuxserver.io/v1/images/$lsio_name/tags" || echo "")
      if [[ -n "$api_response" ]]; then
        latest_version=$(echo "$api_response" | 
                        jq -r '.tags[] | select(.name != "latest") | .name' | 
                        grep -E '^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$' | 
                        sort -Vr | head -n1)
      fi
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
      local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
      local package=$(echo "$image_name" | cut -d/ -f4)
      local token=$(curl -sS --fail "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token // empty')
      if [[ -n "$token" ]]; then
        latest_version=$(curl -sS --fail -H "Authorization: Bearer $token" \
                         "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
                         jq -r '.tags[] | select(. != "latest" and (. | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$")))' | \
                         sort -Vr | head -n1)
      fi
    else
      local namespace=$(echo "$image_name" | cut -d/ -f1)
      local repo=$(echo "$image_name" | cut -d/ -f2)
      if [[ "$namespace" == "$repo" ]]; then
        local api_response=$(curl -sS --fail "https://registry.hub.docker.com/v2/repositories/library/$repo/tags/" || echo "")
        if [[ -n "$api_response" ]]; then
          latest_version=$(echo "$api_response" | 
                          jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                          sort -Vr | head -n1)
        fi
      else
        local api_response=$(curl -sS --fail "https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/" || echo "")
        if [[ -n "$api_response" ]]; then
          latest_version=$(echo "$api_response" | 
                          jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                          sort -Vr | head -n1)
        fi
      fi
    fi

    # Validate and sanitize the version
    if [[ -n "$latest_version" && "$latest_version" != "null" ]]; then
      latest_version=$(sanitize_version "$latest_version")
      
      if validate_version_tag "$latest_version"; then
        break
      else
        log "$COLOR_YELLOW" "⚠️ Invalid version format '$latest_version' for $image, retrying..."
        latest_version=""
      fi
    fi
    
    [[ $i -lt $retries ]] && sleep 5
  done

  if [[ -z "$latest_version" || "$latest_version" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Using 'latest' tag for $image after $retries retries"
    echo "latest"
  else
    echo "$latest_version"
  fi
}

update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    
    [[ "$addon_name" == "updater" ]] && {
        log "$COLOR_BLUE" "🔧 Skipping updater addon (self)"
        return
    }

    log "$COLOR_CYAN" "🔍 Checking add-on: $addon_name"

    local config_file="$addon_path/config.json"
    local build_file="$addon_path/build.json"
    local updater_file="$addon_path/updater.json"

    # Initialize with safe defaults
    local image="" slug="$addon_name" current_version="latest" upstream_version="latest" last_update="Never"

    # Load current config with validation
    if [[ -f "$config_file" ]]; then
        if ! verify_config_version "$config_file"; then
            log "$COLOR_RED" "❌ Existing config.json has invalid version, resetting to 'latest'"
            current_version="latest"
        else
            current_version=$(sanitize_version "$(safe_jq "$config_file" '.version' 'latest')")
            image=$(safe_jq "$config_file" '.image' "")
            slug=$(safe_jq "$config_file" '.slug' "$addon_name")
        fi
    fi

    if [[ -z "$image" && -f "$build_file" ]]; then
        log "$COLOR_BLUE" "   Checking build.json"
        local arch=$(uname -m)
        [[ "$arch" == "x86_64" ]] && arch="amd64"
        image=$(safe_jq "$build_file" ".build_from.$arch // .build_from.amd64 // .build_from" "")
    fi

    if [[ -z "$image" ]]; then
        log "$COLOR_YELLOW" "⚠️ No Docker image found in config.json or build.json"
        image="$slug:latest"
    fi

    local update_time=$(date '+%Y-%m-%d %H:%M:%S')
    if [[ -f "$updater_file" ]]; then
        if ! jq --arg image "$image" --arg slug "$slug" \
           '.image = $image | .slug = $slug' "$updater_file" > "${updater_file}.tmp" 2>/dev/null || \
           ! mv "${updater_file}.tmp" "$updater_file"; then
           log "$COLOR_RED" "❌ Failed to update updater.json"
        fi
    else
        if ! jq -n --arg slug "$slug" --arg image "$image" \
            --arg upstream "latest" --arg updated "$update_time" \
            '{
                slug: $slug,
                image: $image,
                upstream_version: $upstream,
                last_update: $updated
            }' > "$updater_file" 2>/dev/null; then
            log "$COLOR_RED" "❌ Failed to create updater.json"
        fi
    fi

    upstream_version=$(sanitize_version "$(safe_jq "$updater_file" '.upstream_version' 'latest')")
    last_update=$(safe_jq "$updater_file" '.last_update' "Never")

    log "$COLOR_BLUE" "   Current version: $current_version"
    log "$COLOR_BLUE" "   Docker image: $image"
    log "$COLOR_BLUE" "   Last update: $last_update"

    # Get and validate new version
    local latest_version=""
    for ((i=1; i<=3; i++)); do
        latest_version=$(get_latest_docker_tag "$image")
        latest_version=$(sanitize_version "$latest_version")
        
        if validate_version_tag "$latest_version"; then
            break
        fi
        [[ $i -lt 3 ]] && sleep 5
    done

    [[ -z "$latest_version" ]] && latest_version="latest"

    # Triple-check before writing
    if [[ "$latest_version" != "$current_version" ]]; then
        log "$COLOR_GREEN" "⬆️ Update available: $current_version → $latest_version"
        
        [[ "$DRY_RUN" == "true" ]] && {
            log "$COLOR_CYAN" "🛑 Dry run enabled - would update to $latest_version"
            return
        }

        # Write with validation
        if [[ -f "$config_file" ]]; then
            if write_safe_version "$config_file" "$latest_version"; then
                log "$COLOR_GREEN" "✅ Verified version update in config.json"
            else
                log "$COLOR_RED" "❌ Failed to safely update config.json"
            fi
        fi

        # Update updater.json with same validation
        if [[ -f "$updater_file" ]]; then
            if jq --arg v "$latest_version" --arg dt "$update_time" \
                '.upstream_version = $v | .last_update = $dt' "$updater_file" > "${updater_file}.tmp" && \
                mv "${updater_file}.tmp" "$updater_file"; then
                
                if verify_config_version "$updater_file"; then
                    log "$COLOR_GREEN" "✅ Verified version update in updater.json"
                else
                    log "$COLOR_RED" "❌ Failed to validate updater.json version"
                fi
            else
                log "$COLOR_RED" "❌ Failed to update updater.json"
            fi
        fi

        update_changelog "$addon_path" "$slug" "$current_version" "$latest_version" "$image"
    else
        log "$COLOR_GREEN" "✔️ Already up to date"
    fi
}

# ... (rest of the functions remain the same as previous version) ...

# Main execution
log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"

# Load configuration
if [[ ! -f "$CONFIG_PATH" ]]; then
  log "$COLOR_RED" "❌ Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(safe_jq "$CONFIG_PATH" '.github_repo' "")
GITHUB_USERNAME=$(safe_jq "$CONFIG_PATH" '.github_username' "")
GITHUB_TOKEN=$(safe_jq "$CONFIG_PATH" '.github_token' "")
CHECK_CRON=$(safe_jq "$CONFIG_PATH" '.check_cron' "0 */6 * * *")
STARTUP_CRON=$(safe_jq "$CONFIG_PATH" '.startup_cron' "")
TIMEZONE=$(safe_jq "$CONFIG_PATH" '.timezone' "UTC")
MAX_LOG_LINES=$(safe_jq "$CONFIG_PATH" '.max_log_lines' "1000")
DRY_RUN=$(safe_jq "$CONFIG_PATH" '.dry_run' "false")
SKIP_PUSH=$(safe_jq "$CONFIG_PATH" '.skip_push' "false")

# Load notification config
NOTIFICATION_ENABLED=$(safe_jq "$CONFIG_PATH" '.notifications_enabled' "false")
if [[ "$NOTIFICATION_ENABLED" == "true" ]]; then
  NOTIFICATION_SERVICE=$(safe_jq "$CONFIG_PATH" '.notification_service' "")
  NOTIFICATION_URL=$(safe_jq "$CONFIG_PATH" '.notification_url' "")
  NOTIFICATION_TOKEN=$(safe_jq "$CONFIG_PATH" '.notification_token' "")
  NOTIFICATION_TO=$(safe_jq "$CONFIG_PATH" '.notification_to' "")
  NOTIFY_ON_SUCCESS=$(safe_jq "$CONFIG_PATH" '.notify_on_success' "false")
  NOTIFY_ON_ERROR=$(safe_jq "$CONFIG_PATH" '.notify_on_error' "true")
  NOTIFY_ON_UPDATES=$(safe_jq "$CONFIG_PATH" '.notify_on_updates' "true")
fi

export TZ="$TIMEZONE"

# First run on startup
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check

# Main loop
log "$COLOR_GREEN" "⏳ Waiting for cron triggers..."
while true; do
  if [[ -n "$STARTUP_CRON" ]] && should_run_from_cron "$STARTUP_CRON"; then
    log "$COLOR_BLUE" "⏰ Startup cron triggered ($STARTUP_CRON)"
    perform_update_check
  fi

  if should_run_from_cron "$CHECK_CRON"; then
    log "$COLOR_BLUE" "⏰ Check cron triggered ($CHECK_CRON)"
    perform_update_check
  fi

  sleep 60
done
