#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
RUN_MARKER="/data/.has_run"
MAX_LOG_FILES=5
MAX_LOG_LINES=5000

# ======================
# INITIALIZATION
# ======================
declare -A ADDON_STATUS
declare -A NOTIFICATION_SETTINGS=(
    [enabled]=false
    [service]=""
    [url]=""
    [token]=""
    [to]=""
    [on_success]=false
    [on_error]=true
    [on_updates]=true
)

# ======================
# LOGGING SYSTEM
# ======================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_CYAN="\033[0;36m"

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

log_debug() { [ "$DEBUG" = "true" ] && log_with_timestamp "$COLOR_CYAN" "🐛 $*"; }
log_info() { log_with_timestamp "$COLOR_BLUE" "ℹ️ $*"; }
log_success() { log_with_timestamp "$COLOR_GREEN" "✅ $*"; }
log_warning() { log_with_timestamp "$COLOR_YELLOW" "⚠️ $*"; }
log_error() { log_with_timestamp "$COLOR_RED" "❌ $*"; }

# ======================
# LOCK MANAGEMENT
# ======================
acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
        log_error "Another instance is running (PID: $pid)"
        exit 1
    fi
    echo $$ >&9
    log_debug "Acquired lock"
}

release_lock() {
    flock -u 9
    exec 9>&-
    rm -f "$LOCK_FILE"
    log_debug "Released lock"
}

# ======================
# NOTIFICATION SYSTEM
# ======================
validate_notification_config() {
    case "${NOTIFICATION_SETTINGS[service]}" in
        "gotify")
            [[ -z "${NOTIFICATION_SETTINGS[url]}" || -z "${NOTIFICATION_SETTINGS[token]}" ]] && {
                log_warning "Invalid Gotify config - missing URL or token"
                return 1
            }
            ;;
        "ntfy")
            [[ -z "${NOTIFICATION_SETTINGS[url]}" ]] && {
                log_warning "Invalid ntfy config - missing URL"
                return 1
            }
            ;;
        *)
            log_warning "Unsupported notification service"
            return 1
            ;;
    esac
    return 0
}

send_notification() {
    [ "${NOTIFICATION_SETTINGS[enabled]}" = "false" ] && return
    validate_notification_config || return

    local title="$1"
    local message="$2"
    local priority="${3:-0}"

    log_debug "Sending notification via ${NOTIFICATION_SETTINGS[service]}"

    case "${NOTIFICATION_SETTINGS[service]}" in
        "gotify")
            curl -sSf --connect-timeout 10 -X POST \
                -H "Content-Type: application/json" \
                -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
                "${NOTIFICATION_SETTINGS[url]}/message?token=${NOTIFICATION_SETTINGS[token]}" >> "$LOG_FILE" 2>&1 || {
                log_error "Gotify notification failed"
                return 1
            }
            ;;
        "ntfy")
            curl -sSf --connect-timeout 10 -X POST \
                -H "Title: $title" \
                -H "Priority: $priority" \
                -d "$message" \
                "${NOTIFICATION_SETTINGS[url]}" >> "$LOG_FILE" 2>&1 || {
                log_error "ntfy notification failed"
                return 1
            }
            ;;
    esac
}

generate_summary() {
    local updated=0 up_to_date=0 errors=0
    local message="📋 **Add-on Update Report**\n\n"
    
    for addon in "${!ADDON_STATUS[@]}"; do
        IFS='|' read -r current latest status <<< "${ADDON_STATUS[$addon]}"
        
        case "$status" in
            "updated") 
                message+="✅ $addon: $current → $latest\n"
                ((updated++))
                ;;
            "up_to_date")
                message+="🔹 $addon: $current (latest)\n"
                ((up_to_date++))
                ;;
            "no_image")
                message+="⚪ $addon: No image configured\n"
                ;;
            "check_failed")
                message+="❌ $addon: Version check failed\n"
                ((errors++))
                ;;
            *)
                message+="❓ $addon: Unknown status\n"
                ((errors++))
                ;;
        esac
    done

    message+="\n**Summary:** $updated updated, $up_to_date current, $errors errors"
    echo "$message"
}

# ======================
# VERSION CHECKING
# ======================
get_latest_docker_tag() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    local cache_file="/tmp/docker_tags_$(echo "$image_name" | tr '/:' '_').cache"
    local cache_age=3600  # 1 hour cache

    # Cache check
    if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt $cache_age ]; then
        log_debug "Using cached version for $image_name"
        cat "$cache_file"
        return 0
    fi

    log_debug "Fetching fresh version for $image_name"
    local version=""

    # LinuxServer.io images
    if [[ "$image_name" =~ ^linuxserver/ ]]; then
        version=$(curl -sSf --connect-timeout 10 \
            "https://api.linuxserver.io/v1/images/${image_name#linuxserver/}/tags" | \
            jq -r '.tags[] | select(.name != "latest") | .name' | sort -Vr | head -n1)
    
    # GitHub Container Registry
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
        local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
        local package=$(echo "$image_name" | cut -d/ -f4)
        version=$(curl -sSf --connect-timeout 10 \
            "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
            jq -r '.tags[] | select(. != "latest")' | sort -Vr | head -n1)
    
    # Docker Hub
    else
        local namespace=$(echo "$image_name" | cut -d/ -f1)
        local repo=$(echo "$image_name" | cut -d/ -f2)
        [ "$namespace" = "$repo" ] && namespace="library"
        
        version=$(curl -sSf --connect-timeout 10 \
            "https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/" | \
            jq -r '.results[] | select(.name != "latest") | .name' | sort -Vr | head -n1)
    fi

    [ -n "$version" ] && echo "$version" > "$cache_file"
    echo "${version:-latest}"
}

# ======================
# ADD-ON PROCESSING
# ======================
process_addon() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    [ "$addon_name" = "updater" ] && return

    local image="" current_version="latest" status="unknown"
    local config_file="$addon_path/config.json"
    local build_file="$addon_path/build.json"

    # Extract current version
    if [ -f "$config_file" ]; then
        image=$(jq -r '.image // empty' "$config_file" 2>/dev/null || true)
        current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null || echo "latest")
    fi

    # Fallback to build.json
    if [ -z "$image" ] && [ -f "$build_file" ]; then
        local arch=$(uname -m)
        [ "$arch" = "x86_64" ] && arch="amd64"
        image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | if type=="string" then . else empty end' "$build_file" 2>/dev/null || true)
    fi

    # Check if image was found
    if [ -z "$image" ]; then
        log_warning "No Docker image configured for $addon_name"
        ADDON_STATUS["$addon_name"]="$current_version||no_image"
        return
    fi

    # Get latest version
    local latest_version
    if ! latest_version=$(get_latest_docker_tag "$image"); then
        log_error "Failed to check version for $addon_name"
        ADDON_STATUS["$addon_name"]="$current_version||check_failed"
        return
    fi

    # Version comparison
    if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
        status="updated"
        log_success "Update available: $addon_name ($current_version → $latest_version)"
        
        # Apply update if not dry run
        [ "$DRY_RUN" = "false" ] && {
            if jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp"; then
                mv "$config_file.tmp" "$config_file"
                log_info "Updated $addon_name to $latest_version"
            else
                log_error "Failed to update $addon_name config"
                status="check_failed"
            fi
        }
    else
        status="up_to_date"
        log_info "$addon_name is current ($current_version)"
    fi

    ADDON_STATUS["$addon_name"]="$current_version|$latest_version|$status"
}

# ======================
# MAIN EXECUTION FLOW
# ======================
load_config() {
    [ ! -f "$CONFIG_PATH" ] && {
        log_error "Config file not found at $CONFIG_PATH"
        exit 1
    }

    # Load core settings
    DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
    DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
    local clear_marker=$(jq -r '.clear_marker_on_restart // true' "$CONFIG_PATH")

    # Notification settings
    NOTIFICATION_SETTINGS[enabled]=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
    NOTIFICATION_SETTINGS[service]=$(jq -r '.notification_service // "ntfy"' "$CONFIG_PATH")
    NOTIFICATION_SETTINGS[url]=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
    NOTIFICATION_SETTINGS[token]=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
    NOTIFICATION_SETTINGS[to]=$(jq -r '.notification_to // ""' "$CONFIG_PATH")

    # Clear run marker if configured
    [ "$clear_marker" = "true" ] && rm -f "$RUN_MARKER"

    log_debug "Configuration loaded"
}

rotate_logs() {
    [ -f "$LOG_FILE" ] && {
        local log_size=$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)
        [ "$log_size" -gt $((MAX_LOG_LINES * 100)) ] && {
            log_info "Rotating log file"
            gzip -c "$LOG_FILE" > "$LOG_FILE.$(date +%Y%m%d%H%M%S).gz"
            > "$LOG_FILE"
            ls -t "$LOG_FILE".*.gz | tail -n +$((MAX_LOG_FILES + 1)) | xargs rm -f --
        }
    }
}

main() {
    rotate_logs
    load_config

    # Single-run check
    [ -f "$RUN_MARKER" ] && {
        log_info "Add-on already executed this boot. Set clear_marker_on_restart=false to override."
        exit 0
    }

    # Start main workflow
    acquire_lock
    touch "$RUN_MARKER"
    trap "release_lock" EXIT

    log_info "Starting add-on version checks"
    
    # Process each add-on
    for addon in "$REPO_DIR"/*/; do
        [ -d "$addon" ] && process_addon "$addon"
    done

    # Send summary notification
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        local summary=$(generate_summary)
        send_notification "Add-on Update Summary" "$summary" 0
    fi

    log_success "Completed all checks"
    exit 0
}

main