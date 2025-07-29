#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
MAX_LOG_FILES=5
MAX_LOG_LINES=10000

# ======================
# COLOR DEFINITIONS
# ======================
COLOR_RESET="\033[0m"
COLOR_RED="\033[0;31m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[0;33m"
COLOR_BLUE="\033[0;34m"
COLOR_CYAN="\033[0;36m"

# ======================
# NOTIFICATION SETTINGS
# ======================
declare -A NOTIFICATION_SETTINGS=(
    [enabled]=false
    [service]=""
    [url]=""
    [token]=""
    [on_success]=false
    [on_error]=true
    [on_updates]=true
)

# ======================
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS=()
declare -A UNCHANGED_ADDONS=()

# ======================
# LOGGING FUNCTIONS
# ======================
log() {
    local color="$1"
    shift
    echo -e "${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

log_with_timestamp() {
    local color="$1"
    shift
    echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

log_error() { log_with_timestamp "$COLOR_RED" "❌ $*"; }
log_warning() { log_with_timestamp "$COLOR_YELLOW" "⚠️ $*"; }
log_info() { log_with_timestamp "$COLOR_BLUE" "ℹ️ $*"; }
log_success() { log_with_timestamp "$COLOR_GREEN" "✅ $*"; }
log_debug() { [ "$DEBUG" = "true" ] && log_with_timestamp "$COLOR_CYAN" "🐛 $*"; }

# ======================
# LOCK MANAGEMENT
# ======================
acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
        log_error "Another update process (PID $pid) is running. Exiting."
        exit 1
    fi
    echo $$ >&9
}

release_lock() {
    flock -u 9
    exec 9>&-
    rm -f "$LOCK_FILE"
}

# ======================
# NOTIFICATION SERVICE
# ======================
send_notification() {
    [ "${NOTIFICATION_SETTINGS[enabled]}" != "true" ] && return 0

    local title="$1"
    local message="$2"
    local priority="${3:-0}"
    local service="${NOTIFICATION_SETTINGS[service]}"
    local url="${NOTIFICATION_SETTINGS[url]%/}"  # Remove trailing slash
    local max_retries=2
    local attempt=0

    # JSON escape the message
    message=$(jq -aRs . <<< "$message" | sed 's/^"//;s/"$//')

    while [ $attempt -lt $max_retries ]; do
        attempt=$((attempt+1))
        log_debug "Notification attempt $attempt/$max_retries to $service"

        case "$service" in
            gotify)
                local full_url="${url}/message?token=${NOTIFICATION_SETTINGS[token]}"
                local curl_cmd=(
                    curl -sSf -X POST
                    -H "Content-Type: application/json"
                    -d "{\"title\":\"$title\", \"message\":$message, \"priority\":$priority}"
                    --connect-timeout 10
                    --max-time 15
                    --retry 2
                    --retry-delay 1
                    "$full_url"
                )
                ;;

            ntfy)
                local full_url="${url}/${NOTIFICATION_SETTINGS[to]}"
                local curl_cmd=(
                    curl -sSf -X POST
                    -H "Content-Type: application/json"
                    -d "{\"title\":\"$title\", \"message\":$message, \"priority\":$priority}"
                    --connect-timeout 10
                    "$full_url"
                )
                ;;

            *)
                log_error "Unsupported notification service: $service"
                return 1
                ;;
        esac

        if "${curl_cmd[@]}" >> "$LOG_FILE" 2>&1; then
            log_debug "Notification sent successfully"
            return 0
        else
            log_warning "Notification attempt $attempt failed"
            sleep 1
        fi
    done

    log_error "Failed to send notification after $max_retries attempts"
    return 1
}

# ======================
# VERSION MANAGEMENT
# ======================
get_latest_docker_tag() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    local cache_file="/tmp/docker_tags_$(echo "$image_name" | tr '/:' '_').cache"
    local cache_age=14400  # 4 hours

    # Check cache first
    if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt $cache_age ]; then
        local version=$(cat "$cache_file")
        log_debug "Using cached version for $image_name: $version"
        echo "$version"
        return
    fi

    # Actual version checking logic
    local version=""
    if [[ "$image_name" =~ ^linuxserver/|^lscr.io/linuxserver/ ]]; then
        version=$(get_lsio_tag "$image_name")
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
        version=$(get_ghcr_tag "$image_name")
    else
        version=$(get_dockerhub_tag "$image_name")
    fi

    [[ -z "$version" ]] && version="latest"
    echo "$version" > "$cache_file"
    echo "$version"
}

# ... (include all your original get_lsio_tag, get_ghcr_tag, get_dockerhub_tag functions here)

# ======================
# ADDON PROCESSING
# ======================
update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    
    [ "$addon_name" = "updater" ] && {
        log_info "Skipping self-update check"
        UNCHANGED_ADDONS["$addon_name"]="Skipped self-update"
        return
    }

    log_info "Processing addon: $addon_name"

    local image="" current_version="latest"
    local config_file="$addon_path/config.json"
    local build_file="$addon_path/build.json"

    # Get current version
    [ -f "$config_file" ] && {
        image=$(jq -r '.image // empty' "$config_file" 2>/dev/null || true)
        current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null || echo "latest")
    }

    [ -z "$image" ] && [ -f "$build_file" ] && {
        local arch=$(uname -m)
        [ "$arch" = "x86_64" ] && arch="amd64"
        [ -s "$build_file" ] && 
            image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | if type=="string" then . else empty end' "$build_file" 2>/dev/null || true)
    }

    [ -z "$image" ] && {
        log_warning "No Docker image found for $addon_name"
        UNCHANGED_ADDONS["$addon_name"]="No Docker image"
        return
    }

    local latest_version
    if ! latest_version=$(get_latest_docker_tag "$image"); then
        log_warning "Version check failed for $addon_name"
        UNCHANGED_ADDONS["$addon_name"]="Version check failed"
        return
    fi

    [ -z "$latest_version" ] && latest_version="latest"

    log_info "Current: $current_version, Available: $latest_version"

    if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
        log_success "Update available: $current_version → $latest_version"
        UPDATED_ADDONS["$addon_name"]="$current_version → $latest_version"
        
        [ "$DRY_RUN" != "true" ] && {
            update_config_file "$addon_path/config.json" "$latest_version" "$addon_name" "config.json"
            update_changelog "$addon_path" "$addon_name" "$current_version" "$latest_version" "$image"
        }
    else
        log_info "Already up-to-date"
        UNCHANGED_ADDONS["$addon_name"]="Current: $current_version"
    fi
}

# ======================
# GIT OPERATIONS
# ======================
commit_and_push_changes() {
    cd "$REPO_DIR" || return 1

    if [ -n "$(git status --porcelain)" ]; then
        git add .
        
        if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
            log_success "Changes committed"
            
            [ "$SKIP_PUSH" = "true" ] && {
                log_info "Skipping push (skip_push enabled)"
                return 0
            }

            if git push origin main >> "$LOG_FILE" 2>&1; then
                log_success "Changes pushed"
                return 0
            else
                log_error "Push failed"
                return 1
            fi
        else
            log_error "Commit failed"
            return 1
        fi
    else
        log_info "No changes to commit"
    fi
    return 0
}

# ======================
# MAIN WORKFLOW
# ======================
main_workflow() {
    local start_time=$(date +%s)
    log_info "Starting main workflow"

    # Process all addons
    for addon_path in "$REPO_DIR"/*/; do
        [ -d "$addon_path" ] && update_addon_if_needed "$addon_path"
    done

    # Commit changes if needed
    commit_and_push_changes || {
        log_error "Failed to commit/push changes"
        [ "${NOTIFICATION_SETTINGS[on_error]}" = "true" ] && 
            send_notification "Add-on Updater Error" "Failed to push changes to repository" 5
    }

    # Send summary notification
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        local summary="Add-on Update Summary\n\n"
        
        if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
            summary+="✅ Updated (${#UPDATED_ADDONS[@]}):\n"
            for addon in "${!UPDATED_ADDONS[@]}"; do
                summary+="  - $addon: ${UPDATED_ADDONS[$addon]}\n"
            done
        else
            summary+="ℹ️ No add-ons updated\n"
        fi

        summary+="\nUnchanged (${#UNCHANGED_ADDONS[@]}):\n"
        for addon in "${!UNCHANGED_ADDONS[@]}"; do
            summary+="  - $addon: ${UNCHANGED_ADDONS[$addon]}\n"
        done

        summary+="\nDuration: $(( $(date +%s) - start_time ))s"
        
        send_notification "Add-on Update Report" "$summary" 1
    fi

    log_info "Workflow completed in $(( $(date +%s) - start_time )) seconds"
}

# ======================
# ENTRY POINT
# ======================
main() {
    trap 'release_lock; exit' EXIT TERM INT
    acquire_lock
    load_config
    
    log_info "=== Starting Add-on Updater ==="
    log_info "System time: $(date)"
    log_info "Timezone: $(date +%Z)"
    
    main_workflow
    
    log_info "=== Process Complete ==="
    log_info "Sleeping indefinitely..."
    while true; do sleep 3600; done
}

main