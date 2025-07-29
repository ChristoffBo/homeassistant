#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
RUN_MARKER="/data/.has_run"  # Ensures single execution
MAX_LOG_FILES=5
MAX_LOG_LINES=1000

# ======================
# GLOBAL STATE
# ======================
declare -A ADDON_STATUS      # Tracks all add-on version states
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
# COLOR LOGGING
# ======================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

# ======================
# FUNCTIONS
# ======================

# --- Logging ---
log() {
    local color="$1"; shift
    echo -e "${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

log_with_timestamp() {
    local color="$1"; shift
    echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

log_error()    { log_with_timestamp "$COLOR_RED"    "❌ $*"; }
log_warning()  { log_with_timestamp "$COLOR_YELLOW" "⚠️ $*"; }
log_info()     { log_with_timestamp "$COLOR_BLUE"   "ℹ️ $*"; }
log_success()  { log_with_timestamp "$COLOR_GREEN"  "✅ $*"; }

# --- Lock Management ---
acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
        log_error "Another instance is running (PID $pid). Exiting."
        exit 1
    fi
    echo $$ >&9
}

release_lock() {
    flock -u 9
    exec 9>&-
    rm -f "$LOCK_FILE"
}

# --- Notifications ---
send_notification() {
    [ "${NOTIFICATION_SETTINGS[enabled]}" = "false" ] && return

    local title="$1"
    local message="$2"
    local priority="${3:-0}"

    case "${NOTIFICATION_SETTINGS[service]}" in
        "gotify")
            curl -sSf -X POST \
                -H "Content-Type: application/json" \
                -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
                "${NOTIFICATION_SETTINGS[url]}/message?token=${NOTIFICATION_SETTINGS[token]}" >> "$LOG_FILE" 2>&1 || \
                log_error "Gotify notification failed"
            ;;
        "ntfy")
            curl -sSf -X POST \
                -H "Title: $title" \
                -H "Priority: $priority" \
                -d "$message" \
                "${NOTIFICATION_SETTINGS[url]}" >> "$LOG_FILE" 2>&1 || \
                log_error "ntfy notification failed"
            ;;
        *)
            log_warning "Unsupported service: ${NOTIFICATION_SETTINGS[service]}"
            ;;
    esac
}

send_summary_notification() {
    local message="📋 **Add-on Update Report**\n\n"
    local updated=0 up_to_date=0 errors=0

    for addon in "${!ADDON_STATUS[@]}"; do
        IFS='|' read -r current latest status <<< "${ADDON_STATUS[$addon]}"
        case "$status" in
            "updated")    message+="✅ $addon: $current → $latest\n"; ((updated++)) ;;
            "up_to_date") message+="🔹 $addon: $current (latest)\n"; ((up_to_date++)) ;;
            *)            message+="❌ $addon: Check failed\n"; ((errors++)) ;;
        esac
    done

    message+="\n**Summary:** $updated updated, $up_to_date current, $errors errors"
    send_notification "Add-on Update Summary" "$message" $((errors > 0 ? 4 : 0))
}

# --- Version Checks ---
get_latest_docker_tag() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    local cache_file="/tmp/docker_tags_$(echo "$image_name" | tr '/:' '_').cache"
    local cache_age=14400  # 4 hours

    # Cache logic
    if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt $cache_age ]; then
        cat "$cache_file"
        return
    fi

    local version=""
    if [[ "$image_name" =~ ^linuxserver/ ]]; then
        version=$(curl -sSf "https://api.linuxserver.io/v1/images/${image_name#linuxserver/}/tags" | 
                  jq -r '.tags[] | select(.name != "latest") | .name' | sort -Vr | head -n1)
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
        version=$(curl -sSf "https://ghcr.io/v2/${image_name#ghcr.io/}/tags/list" | 
                  jq -r '.tags[] | select(. != "latest")' | sort -Vr | head -n1)
    else
        version=$(curl -sSf "https://registry.hub.docker.com/v2/repositories/${image_name}/tags/" | 
                  jq -r '.results[] | select(.name != "latest") | .name' | sort -Vr | head -n1)
    fi

    [ -n "$version" ] && echo "$version" > "$cache_file"
    echo "${version:-latest}"
}

# --- Add-on Processing ---
update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    [ "$addon_name" = "updater" ] && return  # Skip self

    local image="" current_version="latest" status="error"
    local config_file="$addon_path/config.json"

    # Extract current version
    [ -f "$config_file" ] && {
        image=$(jq -r '.image // empty' "$config_file" 2>/dev/null || true)
        current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null || echo "latest")
    }

    # Get latest version
    if [ -n "$image" ]; then
        local latest_version
        if latest_version=$(get_latest_docker_tag "$image"); then
            if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
                status="updated"
                [ "$DRY_RUN" != "true" ] && 
                    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && 
                    mv "$config_file.tmp" "$config_file"
            else
                status="up_to_date"
            fi
        fi
    else
        log_warning "No image found for $addon_name"
    fi

    ADDON_STATUS["$addon_name"]="$current_version|${latest_version:-unknown}|$status"
}

# --- Main Workflow ---
main() {
    # Single-run guard
    [ -f "$RUN_MARKER" ] && { log_info "Already executed. Exiting."; exit 0; }
    touch "$RUN_MARKER"
    trap "rm -f '$RUN_MARKER'; release_lock" EXIT

    # Lock to prevent concurrent runs
    acquire_lock

    # Load config
    if [ -f "$CONFIG_PATH" ]; then
        NOTIFICATION_SETTINGS[enabled]=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[service]=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[url]=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[token]=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
        DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
    fi

    # Process all add-ons
    log_info "Starting version checks..."
    for addon in "$REPO_DIR"/*/; do
        [ -d "$addon" ] && update_addon_if_needed "$addon"
    done

    # Send summary
    [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ] && send_summary_notification
    log_success "Completed all checks"
}

main