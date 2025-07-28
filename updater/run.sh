#!/usr/bin/env bash
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

# Clear log file
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

verify_config_version() {
  local config_file="$1"
  local max_attempts=3
  local attempt=0
  
  while [[ $attempt -lt $max_attempts ]]; do
    local current_version=$(jq -r '.version' "$config_file" 2>/dev/null || echo "")
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
    # Write to temp file first
    if jq --arg v "$version" '.version = $v' "$file" > "$temp_file" 2>/dev/null; then
      # Verify the temp file
      local written_version=$(jq -r '.version' "$temp_file" 2>/dev/null)
      written_version=$(sanitize_version "$written_version")
      
      if [[ "$written_version" == "$version" ]]; then
        mv "$temp_file" "$file"
        if verify_config_version "$file"; then
          return 0
        fi
      fi
    fi
    
    attempt=$((attempt+1))
    log "$COLOR_YELLOW" "⚠️ Version write attempt $attempt/$max_attempts failed for $file"
    sleep 1
  done
  
  log "$COLOR_RED" "❌ Failed to write version to $file after $max_attempts attempts"
  return 1
}

send_notification() {
  # ... (keep existing notification code) ...
}

# ... (keep existing lock file and config loading code) ...

get_latest_docker_tag() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  local latest_version=""
  local retries=3
  
  for ((i=1; i<=retries; i++)); do
    # ... (keep existing tag detection code) ...

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

    local image="" slug="$addon_name" current_version="latest" upstream_version="latest" last_update="Never"
    local config_file="$addon_path/config.json"
    local build_file="$addon_path/build.json"
    local updater_file="$addon_path/updater.json"

    # Load current config with validation
    if [[ -f "$config_file" ]]; then
        if ! verify_config_version "$config_file"; then
            log "$COLOR_RED" "❌ Existing config.json has invalid version, resetting to 'latest'"
            current_version="latest"
        else
            current_version=$(sanitize_version "$(jq -r '.version' "$config_file")")
            image=$(jq -r '.image' "$config_file")
            slug=$(jq -r '.slug' "$config_file")
        fi
    fi

    # ... (rest of existing config loading code) ...

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
            if jq --arg v "$latest_version" --arg dt "$(date '+%Y-%m-%d %H:%M:%S')" \
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

# ... (keep remaining functions and main execution code) ...
