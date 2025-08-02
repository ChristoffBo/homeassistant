#!/usr/bin/env bash
set -euo pipefail

# Fix critical variables
export HOME="/tmp"

# Globals
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log() {
    local msg="$1"
    local prefix="$2"
    local color="$3"
    local timestamp
    timestamp=$(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')
    echo -e "[$timestamp] ${color}${prefix}${NC} $msg"
    echo "[$timestamp] $prefix $msg" >> "$LOG_FILE"
}

info() {
    log "$1" "ℹ️" "$BLUE"
}
success() {
    log "$1" "✅" "$GREEN"
}
warning() {
    log "$1" "⚠️" "$YELLOW"
}
error() {
    log "$1" "❌" "$RED"
}
debug() {
    if [ "$DEBUG" = "true" ]; then
        log "$1" "🐛" "$CYAN"
    fi
}

# Read config
if [ ! -f "$CONFIG_PATH" ]; then
    error "Configuration file not found at $CONFIG_PATH"
    exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
GITEA_REPO=$(jq -r '.gitea_repo // empty' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")

NOTIFICATIONS_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
NOTIFICATION_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
NOTIFICATION_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
NOTIFICATION_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
NOTIFICATION_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
NOTIFY_ON_ERROR=$(jq -r '.notify_on_error // false' "$CONFIG_PATH")
NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates // false' "$CONFIG_PATH")

# Make sure repo dir exists
if [ ! -d "$REPO_DIR" ]; then
    info "Cloning repository..."
    if [ -n "$GITHUB_REPO" ]; then
        git clone --depth=1 "$GITHUB_REPO" "$REPO_DIR"
    elif [ -n "$GITEA_REPO" ]; then
        git clone --depth=1 "$GITEA_REPO" "$REPO_DIR"
    else
        error "No GitHub or Gitea repo URL provided in configuration."
        exit 1
    fi
fi

cd "$REPO_DIR"

# Configure git user/email if needed
git config user.name "Add-on Updater"
git config user.email "updater@example.com"

# Pull latest changes
info "Pulling latest changes from repository..."
if ! git pull origin main --ff-only; then
    error "Git pull failed!"
    if [ "$NOTIFICATIONS_ENABLED" = "true" ] && [ "$NOTIFY_ON_ERROR" = "true" ]; then
        send_notification "Add-on Updater Error" "Git pull failed."
    fi
    exit 1
fi
info "Git pull completed."

# Prepare summary info
UPDATED_ADDONS=()
CHECKED_ADDONS=()

# Add-on check function (simplified example)
check_addon() {
    local addon_name="$1"
    local current_version="$2"
    local docker_image="$3"

    info "Checking add-on: $addon_name"
    CHECKED_ADDONS+=("$addon_name")

    # Simulate fetch of latest version (replace with your actual logic)
    # Here you should implement your improved version fetching/filtering logic
    local available_version="latest"  # placeholder

    # For demo, pretend to compare versions:
    if [ "$available_version" != "$current_version" ]; then
        info "Add-on $addon_name update available: $current_version -> $available_version"
        UPDATED_ADDONS+=("$addon_name ($current_version -> $available_version)")

        if [ "$DRY_RUN" = "false" ]; then
            # Update files logic here
            # Commit and push logic here (respecting $SKIP_PUSH)
            success "Updated $addon_name to version $available_version"
        else
            warning "Dry run enabled - no changes made for $addon_name"
        fi
    else
        info "Add-on $addon_name is already up to date ($current_version)"
    fi
}

# Example list of addons to check (replace with actual dynamic logic)
# You probably want to loop over addons from your repo metadata
# Here's just a hardcoded example:
check_addon "2fauth" "5.6.0" "2fauth/2fauth"
check_addon "gitea" "1.24.3" "ghcr.io/alexbelgium/gitea-{arch}"
check_addon "gotify" "2.6.3" "gotify/server:latest"
# ... repeat for all your add-ons

# Compose notification message
notify_msg="Add-on Update Summary:\n\nChecked Add-ons:\n"
for addon in "${CHECKED_ADDONS[@]}"; do
    notify_msg+=" - $addon\n"
done
if [ ${#UPDATED_ADDONS[@]} -eq 0 ]; then
    notify_msg+="\nNo add-ons were updated."
else
    notify_msg+="\nUpdated Add-ons:\n"
    for updated in "${UPDATED_ADDONS[@]}"; do
        notify_msg+=" - $updated\n"
    done
fi

# Send notification if enabled
send_notification() {
    local title="$1"
    local message="$2"

    if [ "$NOTIFICATIONS_ENABLED" != "true" ]; then
        return
    fi

    case "$NOTIFICATION_SERVICE" in
        gotify)
            debug "Sending Gotify notification to $NOTIFICATION_URL"
            curl -s -X POST "$NOTIFICATION_URL/message?token=$NOTIFICATION_TOKEN" \
                -H "Content-Type: application/json" \
                -d "{\"title\":\"$title\",\"message\":\"$message\",\"priority\":0}" >/dev/null 2>&1 && \
                success "Gotify notification sent" || error "Failed to send Gotify notification"
            ;;
        # Add other services like Apprise, Mailrise here
        *)
            warning "Notification service $NOTIFICATION_SERVICE not supported."
            ;;
    esac
}

# Send summary notification on updates or always if notify_on_success=true
if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
    if [ "$NOTIFY_ON_UPDATES" = "true" ]; then
        send_notification "Add-on Updater: Updates found" "$notify_msg"
    fi
else
    if [ "$NOTIFY_ON_SUCCESS" = "true" ]; then
        send_notification "Add-on Updater: No updates" "$notify_msg"
    fi
fi

success "Add-on update check complete."

# Sleep indefinitely or exit (depending on your usage)
exit 0
