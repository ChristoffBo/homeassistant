#!/bin/sh
#
# Addons Updater Enhanced - Home Assistant Add-ons automatic updater
# Compatible with POSIX shell, no Bash-only features
#

set -eo pipefail

# --------------------------
# CONFIGURATION
# --------------------------
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/repo"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
CHANGELOG_FILE="CHANGELOG.md"

# Colors for terminal output
COLOR_RESET="\033[0m"
COLOR_RED="\033[0;31m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[1;33m"
COLOR_BLUE="\033[0;34m"
COLOR_CYAN="\033[0;36m"

# --------------------------
# GLOBALS (will be loaded from config)
# --------------------------
NOTIF_ENABLED="false"
NOTIF_SERVICE=""
NOTIF_URL=""
NOTIF_TOKEN=""
NOTIF_TO=""
NOTIF_ON_SUCCESS="false"
NOTIF_ON_ERROR="true"
NOTIF_ON_UPDATES="true"
GITHUB_REPO=""
GITHUB_USERNAME=""
GITHUB_TOKEN=""
TIMEZONE="UTC"
DRY_RUN="false"
SKIP_PUSH="false"
CHECK_TIME="0 3 * * *"  # Default cron schedule at 03:00 daily

# --------------------------
# UTILS - Logging
# --------------------------
log() {
    color="$1"
    shift
    timestamp=$(date +"%Y-%m-%d %H:%M:%S %Z")
    msg="$*"
    printf "%b[%s] %s%b\n" "$color" "$timestamp" "$msg" "$COLOR_RESET" | tee -a "$LOG_FILE"
}

log_info() {
    log "$COLOR_BLUE" "INFO: $*"
}
log_success() {
    log "$COLOR_GREEN" "SUCCESS: $*"
}
log_warning() {
    log "$COLOR_YELLOW" "WARNING: $*"
}
log_error() {
    log "$COLOR_RED" "ERROR: $*"
}

# --------------------------
# LOCKING to prevent multiple runs
# --------------------------
acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
        log_error "Another instance (PID $pid) is running. Exiting."
        exit 1
    fi
    echo $$ >&9
}

release_lock() {
    flock -u 9
    exec 9>&-
    rm -f "$LOCK_FILE"
}

# --------------------------
# Load JSON config values (jq must be installed)
# --------------------------
load_config() {
    if [ ! -f "$CONFIG_PATH" ]; then
        log_error "Config file $CONFIG_PATH not found!"
        exit 1
    fi

    NOTIF_ENABLED=$(jq -r '.notifications_enabled // "false"' "$CONFIG_PATH")
    NOTIF_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
    NOTIF_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
    NOTIF_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
    NOTIF_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
    NOTIF_ON_SUCCESS=$(jq -r '.notify_on_success // "false"' "$CONFIG_PATH")
    NOTIF_ON_ERROR=$(jq -r '.notify_on_error // "true"' "$CONFIG_PATH")
    NOTIF_ON_UPDATES=$(jq -r '.notify_on_updates // "true"' "$CONFIG_PATH")
    GITHUB_REPO=$(jq -r '.github_repo // ""' "$CONFIG_PATH")
    GITHUB_USERNAME=$(jq -r '.github_username // ""' "$CONFIG_PATH")
    GITHUB_TOKEN=$(jq -r '.github_token // ""' "$CONFIG_PATH")
    TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
    DRY_RUN=$(jq -r '.dry_run // "false"' "$CONFIG_PATH")
    SKIP_PUSH=$(jq -r '.skip_push // "false"' "$CONFIG_PATH")
    CHECK_TIME=$(jq -r '.check_time // "0 3 * * *"' "$CONFIG_PATH")

    export TZ="$TIMEZONE"

    log_info "Configuration loaded: notifications_enabled=$NOTIF_ENABLED, dry_run=$DRY_RUN, timezone=$TIMEZONE"
}

# --------------------------
# Simple semantic version compare
# Returns 0 if v1 < v2, 1 if v1 == v2, 2 if v1 > v2
# Ignores 'latest' tags and arch prefixes before compare
# --------------------------
version_compare() {
    v1=$1
    v2=$2

    # Normalize: remove arch prefixes (like amd64-)
    norm_v1=$(echo "$v1" | sed 's/^[a-z0-9]*-//')
    norm_v2=$(echo "$v2" | sed 's/^[a-z0-9]*-//')

    # Ignore 'latest'
    [ "$norm_v1" = "latest" ] && norm_v1="0.0.0"
    [ "$norm_v2" = "latest" ] && norm_v2="0.0.0"

    # Split into major minor patch
    # Fallback patch = 0
    IFS=. read -r v1_maj v1_min v1_patch <<EOF
$norm_v1
EOF
    IFS=. read -r v2_maj v2_min v2_patch <<EOF
$norm_v2
EOF

    v1_maj=${v1_maj:-0}
    v1_min=${v1_min:-0}
    v1_patch=${v1_patch:-0}
    v2_maj=${v2_maj:-0}
    v2_min=${v2_min:-0}
    v2_patch=${v2_patch:-0}

    if [ "$v1_maj" -lt "$v2_maj" ]; then return 0; fi
    if [ "$v1_maj" -gt "$v2_maj" ]; then return 2; fi

    if [ "$v1_min" -lt "$v2_min" ]; then return 0; fi
    if [ "$v1_min" -gt "$v2_min" ]; then return 2; fi

    if [ "$v1_patch" -lt "$v2_patch" ]; then return 0; fi
    if [ "$v1_patch" -gt "$v2_patch" ]; then return 2; fi

    return 1
}

# --------------------------
# Fetch latest tag from Docker Hub
# Arguments:
#   1 = image name (e.g. linuxserver/zerotier)
#   2 = timeout seconds (optional, default 30)
# Outputs latest tag to stdout
# --------------------------
fetch_latest_dockerhub_tag() {
    image=$1
    timeout_sec=${2:-30}

    log_info "Fetching Docker Hub tags for $image..."

    tags_json=$(timeout "$timeout_sec" curl -s "https://registry.hub.docker.com/v2/repositories/${image}/tags?page_size=100" || echo "")
    if [ -z "$tags_json" ]; then
        log_warning "No tags found for $image on Docker Hub."
        return 1
    fi

    # Extract tags ignoring 'latest' and sort semver descending (simplified)
    tags=$(printf '%s\n' "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | sort -rV)
    latest_tag=$(printf '%s\n' "$tags" | head -n1)

    printf '%s' "$latest_tag"
}

# --------------------------
# Git clone or pull repo shallow
# --------------------------
git_clone_or_pull() {
    if [ -d "$REPO_DIR/.git" ]; then
        log_info "Git repo exists, pulling latest changes..."
        cd "$REPO_DIR"
        git fetch --all --tags
        git reset --hard origin/main
        cd -
    else
        log_info "Cloning repo $GITHUB_REPO (shallow)..."
        git clone --depth 1 "https://$GITHUB_USERNAME:$GITHUB_TOKEN@github.com/$GITHUB_REPO.git" "$REPO_DIR"
    fi
}

# --------------------------
# Update changelog file per addon
# Arguments:
#   1 = addon directory path
#   2 = new version
# --------------------------
update_changelog() {
    addon_dir=$1
    new_version=$2
    changelog_path="$addon_dir/$CHANGELOG_FILE"

    date_now=$(date +"%Y-%m-%d %H:%M:%S %Z")

    if [ ! -f "$changelog_path" ]; then
        log_info "Creating new CHANGELOG.md for $addon_dir"
        echo "# Changelog for $(basename "$addon_dir")" > "$changelog_path"
    fi

    echo "## Updated to version $new_version - $date_now" >> "$changelog_path"
    echo "- Automatic update by Addons Updater" >> "$changelog_path"
    echo >> "$changelog_path"
}

# --------------------------
# Send notification helper
# Arguments:
#   1 = title
#   2 = message
#   3 = priority (0=success, 3=update, 5=error)
# --------------------------
send_notification() {
    if [ "$NOTIF_ENABLED" != "true" ]; then
        log_info "Notifications disabled, skipping notify"
        return
    fi

    title="$1"
    message="$2"
    priority="${3:-0}"

    case "$priority" in
        0|1)
            [ "$NOTIF_ON_SUCCESS" != "true" ] && return ;;
        3)
            [ "$NOTIF_ON_UPDATES" != "true" ] && return ;;
        5)
            [ "$NOTIF_ON_ERROR" != "true" ] && return ;;
    esac

    case "$NOTIF_SERVICE" in
        gotify)
            if [ -z "$NOTIF_URL" ] || [ -z "$NOTIF_TOKEN" ]; then
                log_error "Gotify URL or token missing"
                return
            fi
            json="{\"title\":\"$title\",\"message\":\"$message\",\"priority\":$priority}"
            curl -sS -X POST -H "Content-Type: application/json" \
                -d "$json" \
                "${NOTIF_URL%/}/message?token=$NOTIF_TOKEN" >/dev/null 2>&1 || log_error "Gotify notification failed"
            ;;
        mailrise)
            if [ -z "$NOTIF_URL" ] || [ -z "$NOTIF_TO" ]; then
                log_error "Mailrise URL or 'to' missing"
                return
            fi
            json="{\"to\":\"$NOTIF_TO\",\"subject\":\"$title\",\"body\":\"$message\"}"
            curl -sS -X POST -H "Content-Type: application/json" \
                -d "$json" \
                "$NOTIF_URL" >/dev/null 2>&1 || log_error "Mailrise notification failed"
            ;;
        apprise)
            if ! command -v apprise >/dev/null 2>&1; then
                log_error "Apprise CLI not found"
                return
            fi
            apprise -t "$title" -b "$message" "$NOTIF_URL" >/dev/null 2>&1 || log_error "Apprise notification failed"
            ;;
        *)
            log_warning "Unknown notification service: $NOTIF_SERVICE"
            ;;
    esac
}

# --------------------------
# Check and update a single addon
# Arguments:
#   1 = addon dir path
# --------------------------
check_update_addon() {
    addon_dir=$1
    addon_name=$(basename "$addon_dir")

    # Read current version from config.json or default "0.0.0"
    if [ -f "$addon_dir/config.json" ]; then
        current_version=$(jq -r '.version // "0.0.0"' "$addon_dir/config.json")
    else
        current_version="0.0.0"
    fi

    # Read image from build.json
    if [ -f "$addon_dir/build.json" ]; then
        image=$(jq -r '.image // empty' "$addon_dir/build.json")
    else
        image=""
    fi

    if [ -z "$image" ]; then
        log_warning "Addon $addon_name missing image info, skipping."
        return
    fi

    log_info "Checking addon $addon_name with image $image, current version $current_version"

    # Fetch latest tag for image (assume Docker Hub for now)
    latest_version=$(fetch_latest_dockerhub_tag "$image") || {
        log_warning "Could not fetch latest tag for $image"
        return
    }

    if [ -z "$latest_version" ]; then
        log_warning "No latest version found for $image"
        return
    fi

    # Compare versions: if latest > current, update needed
    version_compare "$current_version" "$latest_version"
    comp_result=$?

    if [ "$comp_result" = 0 ]; then
        # current < latest => update needed
        log_info "Update available for $addon_name: $current_version -> $latest_version"

        if [ "$DRY_RUN" = "true" ]; then
            log_info "Dry run enabled - not updating $addon_name"
            return
        fi

        # Update config.json with new version
        tmp_config=$(mktemp)
        jq --arg ver "$latest_version" '.version = $ver' "$addon_dir/config.json" > "$tmp_config" && mv "$tmp_config" "$addon_dir/config.json"

        # Update build.json with new image tag
        tmp_build=$(mktemp)
        jq --arg ver "$latest_version" '.image |= sub(":[^:]*$"; ":" + $ver)' "$addon_dir/build.json" > "$tmp_build" && mv "$tmp_build" "$addon_dir/build.json"

        update_changelog "$addon_dir" "$latest_version"

        # Commit changes to git
        if [ "$SKIP_PUSH" != "true" ]; then
            cd "$REPO_DIR"
            git add "$addon_name/config.json" "$addon_name/build.json" "$addon_name/$CHANGELOG_FILE"
            git commit -m "Update $addon_name to version $latest_version"
            git push origin main
            cd -
        fi

        send_notification "Addon Updated" "$addon_name updated to version $latest_version" 3
        log_success "$addon_name updated to version $latest_version"
    else
        log_info "$addon_name is up to date (version $current_version)"
    fi
}

# --------------------------
# Main updater routine
# --------------------------
main() {
    log_info "===== ADDON UPDATER STARTED ====="

    acquire_lock
    load_config

    # Clone or update repo
    git_clone_or_pull

    # Loop over addons (dirs in repo root)
    for addon_dir in "$REPO_DIR"/*; do
        [ -d "$addon_dir" ] || continue
        # Skip updater addon folder itself if named "addons_updater"
        [ "$(basename "$addon_dir")" = "addons_updater" ] && continue

        check_update_addon "$addon_dir"
    done

    release_lock
    log_success "===== ADDON UPDATER FINISHED ====="
}

main "$@"
