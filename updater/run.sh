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
MAX_LOG_LINES=1000

# ======================
# COLOR DEFINITIONS
# ======================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_DARK_BLUE="\033[0;94m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# ======================
# NOTIFICATION SETTINGS
# ======================
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
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS

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
log_debug() { [ "$DEBUG" = "true" ] && log_with_timestamp "$COLOR_PURPLE" "🐛 $*"; }

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
# CONFIGURATION LOADING
# ======================
load_config() {
    if [ ! -f "$CONFIG_PATH" ]; then
        log_error "Config file $CONFIG_PATH not found!"
        exit 1
    fi

    GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
    GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
    GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
    TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
    DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
    SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
    DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")

    NOTIFICATION_SETTINGS[enabled]=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        NOTIFICATION_SETTINGS[service]=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[url]=$(jq -r '.notification_url // ""' "$CONFIG_PATH" | sed 's:/*$::')/
        NOTIFICATION_SETTINGS[token]=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[to]=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_success]=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_error]=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_updates]=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")

        case "${NOTIFICATION_SETTINGS[service]}" in
            "gotify")
                if [ -z "${NOTIFICATION_SETTINGS[url]}" ] || [ -z "${NOTIFICATION_SETTINGS[token]}" ]; then
                    log_error "Gotify configuration incomplete"
                    NOTIFICATION_SETTINGS[enabled]=false
                elif ! curl -sf --connect-timeout 5 "${NOTIFICATION_SETTINGS[url]}health" >/dev/null; then
                    log_error "Gotify server not reachable at ${NOTIFICATION_SETTINGS[url]}health"
                    NOTIFICATION_SETTINGS[enabled]=false
                else
                    log_debug "Gotify health check passed"
                fi
                ;;
            "mailrise"|"ntfy")
                if [ -z "${NOTIFICATION_SETTINGS[url]}" ] || [ -z "${NOTIFICATION_SETTINGS[to]}" ]; then
                    log_error "${NOTIFICATION_SETTINGS[service]} configuration incomplete"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                ;;
            "apprise")
                if [ -z "${NOTIFICATION_SETTINGS[url]}" ]; then
                    log_error "Apprise configuration incomplete"
                    NOTIFICATION_SETTINGS[enabled]=false
                elif ! command -v apprise >/dev/null; then
                    log_error "Apprise CLI not found"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                ;;
            *)
                log_error "Unknown notification service: ${NOTIFICATION_SETTINGS[service]}"
                NOTIFICATION_SETTINGS[enabled]=false
                ;;
        esac
    fi

    export TZ="$TIMEZONE"

    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
        GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#(https?://)#\1$GITHUB_USERNAME:$GITHUB_TOKEN@#")
    else
        GIT_AUTH_REPO="$GITHUB_REPO"
    fi

    log_configuration
}

log_configuration() {
    log_info "========== CONFIGURATION =========="
    log_info "GitHub Repo: $GITHUB_REPO"
    log_info "Dry Run: $DRY_RUN"
    log_info "Skip Push: $SKIP_PUSH"
    log_info "Timezone: $TIMEZONE"
    log_info "Debug Mode: $DEBUG"
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        log_info "Notifications: Enabled (${NOTIFICATION_SETTINGS[service]})"
        log_info "Notify on Success: ${NOTIFICATION_SETTINGS[on_success]}"
        log_info "Notify on Error: ${NOTIFICATION_SETTINGS[on_error]}"
        log_info "Notify on Updates: ${NOTIFICATION_SETTINGS[on_updates]}"
    else
        log_info "Notifications: Disabled"
    fi
    log_info "=================================="
}

# ======================
# VERSION CHECKING (MODIFIED)
# ======================
get_latest_docker_tag() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    local version=""
    local cache_file="/tmp/docker_tags_$(echo "$image_name" | tr '/:' '_').cache"
    local cache_age=14400

    if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt $cache_age ]; then
        version=$(cat "$cache_file")
        log_debug "Using cached version for $image_name: $version"
        echo "$version"
        return
    fi

    if [[ "$image_name" =~ ^linuxserver/|^lscr.io/linuxserver/ ]]; then
        version=$(get_lsio_tag "$image_name")
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
        version=$(get_ghcr_tag "$image_name")
    else
        version=$(get_dockerhub_tag "$image_name")
    fi

    if [[ -z "$version" || "$version" == "latest" ]]; then
        log_warning "No valid version tag found for $image_name. Skipping update."
        echo ""
        return
    fi

    echo "$version" > "$cache_file"
    echo "$version"
}

# (keep your existing get_lsio_tag, get_ghcr_tag, get_dockerhub_tag functions)

# ======================
# ADD-ON PROCESSING (MODIFIED)
# ======================
update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")

    [ "$addon_name" = "updater" ] && {
        log_info "Skipping updater addon (self)"
        return
    }

    (
        log_info "Checking add-on: $addon_name"
        local image="" current_version="latest"
        local config_file="$addon_path/config.json"
        local build_file="$addon_path/build.json"

        [ -f "$config_file" ] && {
            image=$(jq -r '.image // empty' "$config_file")
            current_version=$(jq -r '.version // empty' "$config_file")
        }

        [ -z "$image" ] && [ -f "$build_file" ] && {
            local arch=$(uname -m)
            [ "$arch" = "x86_64" ] && arch="amd64"
            image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from' "$build_file")
        }

        [ -z "$image" ] && {
            log_warning "No Docker image found for $addon_name"
            UNCHANGED_ADDONS["$addon_name"]="No Docker image found"
            return
        }

        local latest_version
        if ! latest_version=$(get_latest_docker_tag "$image"); then
            UNCHANGED_ADDONS["$addon_name"]="Could not determine latest version"
            return
        fi

        [ -z "$latest_version" ] && {
            UNCHANGED_ADDONS["$addon_name"]="No version tag found (only 'latest')"
            return
        }

        log_info "Current: $current_version | Available: $latest_version"

        if [ "$latest_version" != "$current_version" ]; then
            handle_addon_update "$addon_path" "$addon_name" "$current_version" "$latest_version" "$image"
        else
            log_success "$addon_name is up to date"
            UNCHANGED_ADDONS["$addon_name"]="Already up to date"
        fi
    )
}

# ======================
# MAIN ENTRY
# ======================
main() {
    acquire_lock
    load_config

    log_info "Starting Home Assistant Add-on Updater"
    perform_update_check

    release_lock
    log_info "Update process completed."
    exit 0
}

main