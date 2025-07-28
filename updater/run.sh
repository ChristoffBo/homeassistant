#!/usr/bin/env bash
set -euo pipefail

# Configuration paths and files
CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

# Color definitions for logging
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"       # For successful updates/OK status
COLOR_BLUE="\033[0;34m"        # For current version info
COLOR_YELLOW="\033[0;33m"      # For warnings
COLOR_RED="\033[0;31m"         # For errors
COLOR_PURPLE="\033[0;35m"      # For process start/end
COLOR_CYAN="\033[0;36m"        # For debug info
COLOR_WHITE="\033[0;37m"       # For regular info

# Initialize notification variables
declare -A NOTIFICATION=(
    [enabled]=false
    [service]=""
    [url]=""
    [token]=""
    [to]=""
    [on_success]=false
    [on_error]=true
    [on_updates]=true
)

# Clear log file on startup
: > "$LOG_FILE"

# Improved logging function with consistent format
log() {
    local color="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Format: [TIMESTAMP] MESSAGE
    echo -e "${timestamp} ${color}${message}${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Function to validate version tag format
validate_version_tag() {
    local version="$1"
    [[ "$version" =~ ^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$ ]] || \
    [[ "$version" == "latest" ]]
}

# Function to get the latest Docker image tag with improved validation
get_latest_docker_tag() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    local latest_version=""
    local retries=3
    
    for ((i=1; i<=retries; i++)); do
        # Try different methods based on image source
        if [[ "$image_name" =~ ^linuxserver/ ]] || [[ "$image_name" =~ ^lscr.io/linuxserver/ ]]; then
            # For linuxserver.io images
            local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
            local api_response=$(curl -sSf "https://api.linuxserver.io/v1/images/$lsio_name/tags" || true)
            [[ -n "$api_response" ]] && {
                latest_version=$(echo "$api_response" | 
                    jq -r '.tags[] | select(.name != "latest") | .name' | 
                    grep -E '^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$' | 
                    sort -Vr | head -n1)
            }
        elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
            # For GitHub Container Registry
            local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
            local package=$(echo "$image_name" | cut -d/ -f4)
            local token=$(curl -sSf "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token? // empty')
            [[ -n "$token" ]] && {
                latest_version=$(curl -sSf -H "Authorization: Bearer $token" \
                    "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
                    jq -r '.tags[] | select(. != "latest" and (. | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$")))' | \
                    sort -Vr | head -n1)
            }
        else
            # For standard Docker Hub images
            local namespace=$(echo "$image_name" | cut -d/ -f1)
            local repo=$(echo "$image_name" | cut -d/ -f2)
            if [[ "$namespace" == "$repo" ]]; then
                # Official image (library/)
                local api_response=$(curl -sSf "https://registry.hub.docker.com/v2/repositories/library/$repo/tags/" || true)
                [[ -n "$api_response" ]] && {
                    latest_version=$(echo "$api_response" | 
                        jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                        sort -Vr | head -n1)
                }
            else
                # User/org image
                local api_response=$(curl -sSf "https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/" || true)
                [[ -n "$api_response" ]] && {
                    latest_version=$(echo "$api_response" | 
                        jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                        sort -Vr | head -n1)
                }
            fi
        fi

        # Validate the version format
        if [[ -n "$latest_version" && "$latest_version" != "null" ]]; then
            if validate_version_tag "$latest_version"; then
                break
            else
                log "$COLOR_YELLOW" "Invalid version format received, retrying..."
                latest_version=""
            fi
        fi
        
        [[ $i -lt $retries ]] && sleep 5
    done

    # Fallback to 'latest' if version couldn't be determined
    if [[ -z "$latest_version" || "$latest_version" == "null" ]]; then
        log "$COLOR_YELLOW" "Using 'latest' tag for $image after $retries retries"
        echo "latest"
    else
        echo "$latest_version"
    fi
}

# Function to update an add-on if needed
update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    
    # Skip the updater addon itself
    [[ "$addon_name" == "updater" ]] && {
        log "$COLOR_WHITE" "Skipping updater addon (self)"
        return
    }

    log "$COLOR_WHITE" "Checking add-on: $addon_name"

    # Initialize variables
    local image="" slug="$addon_name" current_version="latest" upstream_version="latest" last_update="Never"
    local config_file="$addon_path/config.json" build_file="$addon_path/build.json" updater_file="$addon_path/updater.json"

    # Get info from config.json if exists
    [[ -f "$config_file" ]] && {
        log "$COLOR_CYAN" "  Checking config.json"
        image=$(jq -r '.image | select(.!=null)' "$config_file" 2>/dev/null || true)
        slug=$(jq -r '.slug | select(.!=null)' "$config_file" 2>/dev/null || true)
        current_version=$(jq -r '.version | select(.!=null)' "$config_file" 2>/dev/null || echo "latest")
    }

    # Fallback to build.json if no image found
    [[ -z "$image" && -f "$build_file" ]] && {
        log "$COLOR_CYAN" "  Checking build.json"
        local arch=$(uname -m)
        [[ "$arch" == "x86_64" ]] && arch="amd64"
        image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | if type=="string" then . else empty end' "$build_file" 2>/dev/null || true)
    }

    # Default fallback if no image found
    [[ -z "$image" ]] && {
        log "$COLOR_YELLOW" "  No Docker image found in config.json or build.json"
        image="$slug:latest"
    }

    # Create or update updater.json
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')
    if [[ -f "$updater_file" ]]; then
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

    # Get current info from updater.json
    upstream_version=$(jq -r '.upstream_version | select(.!=null)' "$updater_file" 2>/dev/null || echo "latest")
    last_update=$(jq -r '.last_update | select(.!=null)' "$updater_file" 2>/dev/null || echo "Never")

    log "$COLOR_BLUE" "  Current version: $current_version"
    log "$COLOR_BLUE" "  Docker image: $image"
    log "$COLOR_BLUE" "  Last update: $last_update"

    # Get latest version with validation
    local latest_version=""
    for ((i=1; i<=3; i++)); do
        latest_version=$(get_latest_docker_tag "$image" 2>/dev/null || true)
        [[ -n "$latest_version" && "$latest_version" != "null" ]] && break
        [[ $i -lt 3 ]] && sleep 5
    done

    [[ -z "$latest_version" || "$latest_version" == "null" ]] && {
        log "$COLOR_YELLOW" "  Could not determine latest version after 3 attempts, using 'latest'"
        latest_version="latest"
    }

    log "$COLOR_BLUE" "  Available version: $latest_version"

    if [[ "$latest_version" != "$current_version" ]]; then
        log "$COLOR_GREEN" "  Update available: $current_version → $latest_version"
        
        [[ "${CONFIG[dry_run]}" == "true" ]] && {
            log "$COLOR_CYAN" "  Dry run enabled - would update to $latest_version"
            return
        }

        # Update config.json if exists
        [[ -f "$config_file" ]] && {
            if jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null; then
                mv "$config_file.tmp" "$config_file"
                log "$COLOR_GREEN" "  Updated version in config.json"
            else
                log "$COLOR_RED" "  Failed to update config.json"
            fi
        }

        # Update updater.json
        if jq --arg v "$latest_version" --arg dt "$update_time" \
            '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null; then
            mv "$updater_file.tmp" "$updater_file"
            log "$COLOR_GREEN" "  Updated updater.json"
        fi

        # Update CHANGELOG.md
        update_changelog "$addon_path" "$slug" "$current_version" "$latest_version" "$image"
    else
        log "$COLOR_GREEN" "  Already up to date"
    fi
}

# Main execution
log "$COLOR_PURPLE" "Starting Home Assistant Add-on Updater"
log "$COLOR_WHITE" "Configuration:"
log "$COLOR_WHITE" "  GitHub Repo: ${CONFIG[github_repo]}"
log "$COLOR_WHITE" "  Dry run: ${CONFIG[dry_run]}"
log "$COLOR_WHITE" "  Skip push: ${CONFIG[skip_push]}"
[[ "${NOTIFICATION[enabled]}" == "true" ]] && {
    log "$COLOR_WHITE" "Notifications: Enabled (Service: ${NOTIFICATION[service]})"
} || log "$COLOR_WHITE" "Notifications: Disabled"

# First run on startup
log "$COLOR_PURPLE" "Running initial update check..."
clone_or_update_repo

cd "$REPO_DIR" || exit 1
git config user.email "updater@local"
git config user.name "HomeAssistant Updater"

for addon_path in "$REPO_DIR"/*/; do
    [[ -d "$addon_path" ]] && update_addon_if_needed "$addon_path"
done

log "$COLOR_PURPLE" "Update check completed"
log "$COLOR_WHITE" "Waiting for next scheduled check..."
