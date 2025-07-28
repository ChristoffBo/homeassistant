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

# Notification variables
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

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# [Previous functions remain the same until get_latest_docker_tag]

get_latest_docker_tag() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  local latest_version=""
  local retries=3
  
  # Remove any existing :tag from image name
  image_name=$(echo "$image_name" | cut -d: -f1)
  
  for ((i=1; i<=retries; i++)); do
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

    # If we found a version, break the retry loop
    if [ -n "$latest_version" ] && [ "$latest_version" != "null" ]; then
      # Ensure we never use a date as a version tag
      if [[ "$latest_version" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
        latest_version="latest"
      fi
      break
    fi
    
    if [ $i -lt $retries ]; then
      sleep 5
    fi
  done

  # If we couldn't determine version after retries, use 'latest'
  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Using 'latest' tag for $image after $retries retries"
    echo "latest"
  else
    echo "$latest_version"
  fi
}

update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    
    # Skip the updater addon itself
    if [[ "$addon_name" == "updater" ]]; then
        return
    fi

    log "$COLOR_CYAN" "🔍 Checking add-on: $addon_name"

    # Initialize variables with safe defaults
    local image=""
    local slug="$addon_name"
    local current_version="latest"
    local upstream_version="latest"
    local last_update="Never"
    local config_file="$addon_path/config.json"
    local build_file="$addon_path/build.json"
    local updater_file="$addon_path/updater.json"

    # 1. First try to get info from config.json (if exists and valid)
    if [[ -f "$config_file" ]]; then
        image=$(jq -r '.image | select(.!=null and .!="")' "$config_file" 2>/dev/null || true)
        slug=$(jq -r '.slug | select(.!=null and .!="")' "$config_file" 2>/dev/null || echo "$addon_name")
        current_version=$(jq -r '.version | select(.!=null and .!="")' "$config_file" 2>/dev/null || echo "latest")
    fi

    # 2. If no image found, try build.json (if exists and valid)
    if [[ -z "$image" && -f "$build_file" ]]; then
        local arch=$(uname -m)
        [[ "$arch" == "x86_64" ]] && arch="amd64"
        image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | if type=="string" then . else empty end' "$build_file" 2>/dev/null || true)
    fi

    # 3. Create/update updater.json with the found image
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')
    if [[ -z "$image" ]]; then
        log "$COLOR_YELLOW" "⚠️ No Docker image found in config.json or build.json"
        image="$slug:latest"  # Default fallback
    fi

    # Ensure we don't have any date tags in the image
    if [[ "$image" =~ :[0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
        image=$(echo "$image" | sed 's/:[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}.*$/:latest/')
    fi

    # Create or update updater.json
    if [[ -f "$updater_file" ]]; then
        upstream_version=$(jq -r '.upstream_version | select(.!=null and .!="")' "$updater_file" 2>/dev/null || echo "latest")
        last_update=$(jq -r '.last_update | select(.!=null and .!="")' "$updater_file" 2>/dev/null || echo "Never")
        
        jq --arg image "$image" --arg slug "$slug" \
           '.image = $image | .slug = $slug' "$updater_file" > "$updater_file.tmp" 2>/dev/null && \
        mv "$updater_file.tmp" "$updater_file"
    else
        jq -n --arg slug "$slug" --arg image "$image" \
            --arg upstream "latest" --arg updated "$update_time" \
            '{
                slug: $slug,
                image: $image,
                upstream_version: $upstream,
                last_update: $updated
            }' > "$updater_file" 2>/dev/null
    fi

    log "$COLOR_BLUE" "   Current version: $current_version"
    log "$COLOR_BLUE" "   Docker image: $image"
    log "$COLOR_BLUE" "   Last update: $last_update"

    # Get latest version with retries and proper error handling
    local latest_version=""
    for ((i=1; i<=3; i++)); do
        latest_version=$(get_latest_docker_tag "$image" 2>/dev/null || true)
        if [[ -n "$latest_version" && "$latest_version" != "null" ]]; then
            break
        fi
        [[ $i -lt $3 ]] && sleep 5
    done

    if [[ -z "$latest_version" || "$latest_version" == "null" ]]; then
        log "$COLOR_YELLOW" "⚠️ Could not determine latest version after 3 attempts, using 'latest'"
        latest_version="latest"
    fi

    log "$COLOR_BLUE" "   Available version: $latest_version"

    if [[ "$latest_version" != "$current_version" ]]; then
        log "$COLOR_GREEN" "⬆️ Update available: $current_version → $latest_version"
        
        if [[ "$DRY_RUN" == "true" ]]; then
            log "$COLOR_CYAN" "🛑 Dry run enabled - would update to $latest_version"
            return
        fi

        # Update config.json if exists
        if [[ -f "$config_file" ]]; then
            if jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null; then
                mv "$config_file.tmp" "$config_file"
                log "$COLOR_GREEN" "✅ Updated version in config.json"
            else
                log "$COLOR_RED" "❌ Failed to update config.json"
            fi
        fi

        # Update updater.json
        if jq --arg v "$latest_version" --arg dt "$update_time" \
            '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null; then
            mv "$updater_file.tmp" "$updater_file"
            log "$COLOR_GREEN" "✅ Updated updater.json"
        fi

        # Update CHANGELOG.md
        update_changelog "$addon_path" "$slug" "$current_version" "$latest_version" "$image"
    else
        log "$COLOR_GREEN" "✔️ Already up to date"
    fi
}

# [Rest of the script remains the same...]
