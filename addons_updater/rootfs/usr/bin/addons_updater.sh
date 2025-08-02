#!/bin/sh

set -e

# ======================
# CONFIGURATION & VARS
# ======================

REPO_URL="https://github.com/ChristoffBo/homeassistant.git"
REPO_DIR="/data/repo"
LOG_FILE="/data/updater.log"
LOCK_FILE="/tmp/addons_updater.lock"
MAX_LOG_LINES=5000

DRY_RUN="false"        # Set true for dry run mode (simulate only)
SKIP_PUSH="false"      # Skip git push (can be set true for testing)

# Notification settings loaded from /data/options.json later
declare -A NOTIFICATION_SETTINGS=(
    [enabled]="false"
    [service]=""
    [url]=""
    [token]=""
    [to]=""
    [on_updates]="false"
    [on_success]="false"
)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Initialize associative arrays for tracking
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS

# ======================
# LOGGING FUNCTIONS
# ======================

log() {
    local color="$1"; shift
    local timestamp
    timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    local message="$*"
    echo -e "${color}${timestamp} | ${message}${NC}" | tee -a "$LOG_FILE"
}

log_info()    { log "$CYAN" "[INFO]    $*"; }
log_success() { log "$GREEN" "[SUCCESS] $*"; }
log_warning() { log "$YELLOW" "[WARNING] $*"; }
log_error()   { log "$RED" "[ERROR]   $*"; }

log_debug() {
    # If you want debug logs uncomment next line or add your own debug flag
    # log "$CYAN" "[DEBUG]   $*"
    :
}

# ======================
# LOCK HANDLING
# ======================

acquire_lock() {
    if [ -f "$LOCK_FILE" ]; then
        log_error "Lock file exists ($LOCK_FILE). Another instance might be running. Exiting."
        exit 1
    fi
    echo $$ > "$LOCK_FILE"
}

release_lock() {
    rm -f "$LOCK_FILE"
}

# ======================
# LOAD CONFIGURATION
# ======================

load_config() {
    # Load user options from /data/options.json
    if [ -f /data/options.json ]; then
        DRY_RUN=$(jq -r '.dry_run // "false"' /data/options.json)
        SKIP_PUSH=$(jq -r '.skip_push // "false"' /data/options.json)

        # Notification settings (enable/disable and service details)
        NOTIFICATION_SETTINGS[enabled]=$(jq -r '.notify.enabled // "false"' /data/options.json)
        NOTIFICATION_SETTINGS[service]=$(jq -r '.notify.service // ""' /data/options.json)
        NOTIFICATION_SETTINGS[url]=$(jq -r '.notify.url // ""' /data/options.json)
        NOTIFICATION_SETTINGS[token]=$(jq -r '.notify.token // ""' /data/options.json)
        NOTIFICATION_SETTINGS[to]=$(jq -r '.notify.to // ""' /data/options.json)
        NOTIFICATION_SETTINGS[on_updates]=$(jq -r '.notify.on_updates // "false"' /data/options.json)
        NOTIFICATION_SETTINGS[on_success]=$(jq -r '.notify.on_success // "false"' /data/options.json)

        log_info "Configuration loaded: dry_run=$DRY_RUN, skip_push=$SKIP_PUSH, notifications enabled=${NOTIFICATION_SETTINGS[enabled]}"
    else
        log_warning "/data/options.json not found, using defaults"
    fi
}

# ======================
# GIT FUNCTIONS
# ======================

clone_or_update_repo() {
    if [ ! -d "$REPO_DIR/.git" ]; then
        log_info "Cloning repository $REPO_URL (shallow clone)..."
        git clone --depth 1 "$REPO_URL" "$REPO_DIR"
    else
        log_info "Repository exists, pulling latest changes..."
        cd "$REPO_DIR"
        git reset --hard
        git clean -fd
        git pull --ff-only
    fi
}

# ======================
# DOCKER TAG FETCHERS
# ======================

get_dockerhub_tags() {
    local image="$1"
    local namespace repo api_url

    namespace=$(echo "$image" | cut -d/ -f1)
    repo=$(echo "$image" | cut -d/ -f2)
    if [ "$namespace" = "$repo" ]; then
        # Official library images have no namespace in the tag URL
        api_url="https://registry.hub.docker.com/v2/repositories/library/$repo/tags/?page_size=100"
    else
        api_url="https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/?page_size=100"
    fi

    curl -sSf "$api_url" | jq -r '.results[].name' 2>/dev/null || echo ""
}

get_latest_tag_from_dockerhub() {
    local image="$1"
    local tags
    tags=$(get_dockerhub_tags "$image")

    # Filter out 'latest' and non-semver tags (basic)
    echo "$tags" | grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}$' | grep -v '^latest$' | sort -Vr | head -n1
}

get_latest_tag_from_ghcr() {
    # GHCR requires auth for many repos; you can extend this with token support if needed
    # For simplicity, skipping GHCR support here or you can add later
    echo ""
}

get_latest_tag_from_linuxserverio() {
    # LinuxServer.io tags are in Docker Hub, so handled in get_latest_tag_from_dockerhub
    echo ""
}

get_latest_docker_tag() {
    local image="$1"
    local latest=""

    # Detect registry by image prefix
    case "$image" in
        ghcr.io/*)
            latest=$(get_latest_tag_from_ghcr "$image")
            ;;
        linuxserver/*)
            latest=$(get_latest_tag_from_dockerhub "$image")
            ;;
        *)
            latest=$(get_latest_tag_from_dockerhub "$image")
            ;;
    esac
    echo "$latest"
}

# ======================
# VERSION COMPARISON
# ======================

version_gt() {
    # returns 0 if $1 > $2, else 1
    # Sort version strings using sort -V and check if first is $2
    [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" != "$1" ]
}

# ======================
# ADD-ON PROCESSING
# ======================

process_addons() {
    log_info "Scanning addons in $REPO_DIR..."

    for addon_dir in "$REPO_DIR"/*; do
        [ -d "$addon_dir" ] || continue

        config_json="$addon_dir/config.json"
        if [ ! -f "$config_json" ]; then
            log_debug "Skipping $addon_dir (no config.json)"
            continue
        fi

        addon_name=$(basename "$addon_dir")
        current_version=$(jq -r '.version // empty' "$config_json")
        image=$(jq -r '.image // empty' "$config_json")

        if [ -z "$image" ]; then
            log_warning "Addon $addon_name has no 'image' field in config.json, skipping"
            continue
        fi

        log_info "Addon: $addon_name, current version: $current_version, image: $image"

        latest_version=$(get_latest_docker_tag "$image")

        if [ -z "$latest_version" ]; then
            log_warning "Could not get latest docker tag for $addon_name ($image), skipping"
            continue
        fi

        if [ "$latest_version" = "latest" ]; then
            log_warning "Latest tag for $addon_name image is 'latest', skipping update to avoid ambiguity"
            continue
        fi

        if version_gt "$latest_version" "$current_version"; then
            log_success "Update available for $addon_name: $current_version → $latest_version"
            if [ "$DRY_RUN" = "true" ]; then
                log_info "Dry run: would update $addon_name to $latest_version"
            else
                update_addon_version "$addon_dir" "$latest_version"
                UPDATED_ADDONS["$addon_name"]="$current_version → $latest_version"
            fi
        else
            log_info "$addon_name is up-to-date (version $current_version)"
            UNCHANGED_ADDONS["$addon_name"]="$current_version"
        fi
    done
}

# ======================
# UPDATE ADD-ON VERSION AND CHANGELOG
# ======================

update_addon_version() {
    local addon_dir="$1"
    local new_version="$2"

    config_json="$addon_dir/config.json"
    changelog_file="$addon_dir/CHANGELOG.md"

    log_info "Updating $addon_dir version to $new_version..."

    # Update version in config.json safely
    jq --arg ver "$new_version" '.version = $ver' "$config_json" > "$config_json.tmp" && mv "$config_json.tmp" "$config_json"

    # Update changelog
    if [ ! -f "$changelog_file" ]; then
        echo "# Changelog for $(basename "$addon_dir")" > "$changelog_file"
    fi

    echo "## $new_version - $(date +%Y-%m-%d)" >> "$changelog_file"
    echo "- Updated addon version to $new_version" >> "$changelog_file"
    echo "" >> "$changelog_file"

    log_success "Addon $(basename "$addon_dir") updated to $new_version"
}

# ======================
# GIT COMMIT AND PUSH
# ======================

commit_and_push_changes() {
    if [ "$DRY_RUN" = "true" ]; then
        log_info "Dry run: skipping git commit and push."
        return
    fi

    cd "$REPO_DIR" || exit 1

    if git diff --quiet; then
        log_info "No changes detected, skipping commit."
        return
    fi

    git add .
    git commit -m "Addon updater script updates on $(date '+%Y-%m-%d %H:%M:%S')"
    if [ "$SKIP_PUSH" != "true" ]; then
        git push origin main
        log_success "Changes pushed to remote repository."
    else
        log_info "Git push skipped by configuration."
    fi
}

# ======================
# SEND NOTIFICATIONS
# ======================

send_notification() {
    local title="$1"
    local message="$2"
    local priority="${3:-3}"

    if [ "${NOTIFICATION_SETTINGS[enabled]}" != "true" ]; then
        log_debug "Notifications disabled, skipping send."
        return
    fi

    case "${NOTIFICATION_SETTINGS[service]}" in
        gotify)
            curl -sSf -X POST \
                -H "X-Gotify-Key: ${NOTIFICATION_SETTINGS[token]}" \
                -F "title=$title" \
                -F "message=$message" \
                -F "priority=$priority" \
                "${NOTIFICATION_SETTINGS[url]}message" >/dev/null 2>&1 || log_warning "Failed to send Gotify notification"
            ;;
        mailrise)
            curl -sSf -X POST \
                -H "Content-Type: application/json" \
                -d "{\"to\":\"${NOTIFICATION_SETTINGS[to]}\",\"subject\":\"$title\",\"message\":\"$message\"}" \
                "${NOTIFICATION_SETTINGS[url]}" >/dev/null 2>&1 || log_warning "Failed to send Mailrise notification"
            ;;
        apprise)
            apprise -q -t "$title" -b "$message" "${NOTIFICATION_SETTINGS[url]}" || log_warning "Failed to send Apprise notification"
            ;;
        *)
            log_warning "Unknown notification service: ${NOTIFICATION_SETTINGS[service]}"
            ;;
    esac
}

# ======================
# MAIN EXECUTION
# ======================

main() {
    acquire_lock
    log_info "===== ADDON UPDATER STARTED ====="

    load_config
    clone_or_update_repo

    process_addons

    if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
        log_success "Updated addons:"
        local updates=""
        for addon in "${!UPDATED_ADDONS[@]}"; do
            log_success " - $addon: ${UPDATED_ADDONS[$addon]}"
            updates="$updates$addon: ${UPDATED_ADDONS[$addon]}\n"
        done

        commit_and_push_changes

        if [ "${NOTIFICATION_SETTINGS[on_updates]}" = "true" ]; then
            send_notification "Add-ons Updated" "$updates" 3
        fi
    else
        log_info "No addons required updating."

        if [ "${NOTIFICATION_SETTINGS[on_success]}" = "true" ]; then
            send_notification "Addon Updater" "All addons are up-to-date." 3
        fi
    fi

    log_info "===== ADDON UPDATER FINISHED ====="
    release_lock
}

main "$@"
