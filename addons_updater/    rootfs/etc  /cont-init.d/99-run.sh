#!/usr/bin/env bash
set -eo pipefail

# ========================================
# CONFIGURATION
# ========================================
CONFIG_PATH="/data/options.json"
ADDONS_PATH="/data/addons"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
CHANGELOG_FILE="CHANGELOG.md"

# Load options from GUI
repository=$(jq -r '.repository' "$CONFIG_PATH")
gituser=$(jq -r '.gituser' "$CONFIG_PATH")
gitmail=$(jq -r '.gitmail // "updater@local"' "$CONFIG_PATH")
gitapi=$(jq -r '.gitapi' "$CONFIG_PATH")
dry_run=$(jq -r '.dry_run // false' "$CONFIG_PATH")
verbose=$(jq -r '.verbose // false' "$CONFIG_PATH")

# Notifications
notifications_enabled=$(jq -r '.notifications_enabled // true' "$CONFIG_PATH")
notification_service="gotify"
notification_url=$(jq -r '.notification_url // empty' "$CONFIG_PATH")
notification_token=$(jq -r '.notification_token // empty' "$CONFIG_PATH")
notify_on_updates=true

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# Arrays to collect status
UPDATED_ADDONS=()
NOT_UPDATED_ADDONS=()

# ========================================
# FUNCTIONS
# ========================================

log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

get_latest_tag() {
    local image="$1"
    local tags
    tags=$(curl -s "https://registry.hub.docker.com/v2/repositories/${image}/tags?page_size=100" | jq -r '.results[].name' | grep -v latest)
    echo "$tags" | sort -V | tail -1
}

compare_versions() {
    [ "$1" != "$2" ]
}

send_notification() {
    local title="$1"
    local message="$2"
    if [ "$notifications_enabled" = "true" ]; then
        curl -s -X POST "${notification_url}/message" \
            -F "token=${notification_token}" \
            -F "title=${title}" \
            -F "message=${message}" \
            -F "priority=5" > /dev/null || true
    fi
}

# ========================================
# GIT SETUP
# ========================================

log "${CYAN}🔧 Initializing Git config...${NC}"
cd "$REPO_DIR"
git config --global user.email "$gitmail"
git config --global user.name "$gituser"

# Pull latest
git pull --quiet || true

# ========================================
# PROCESS EACH ADDON
# ========================================

log "${CYAN}🔍 Checking for updates in $REPO_DIR...${NC}"

for addon_dir in "$REPO_DIR"/*/; do
    [ -d "$addon_dir" ] || continue

    ADDON_NAME=$(basename "$addon_dir")
    CONFIG_JSON="${addon_dir}config.json"
    BUILD_JSON="${addon_dir}build.json"

    # Get image
    if [ -f "$CONFIG_JSON" ]; then
        image=$(jq -r '.image // empty' "$CONFIG_JSON")
    elif [ -f "$BUILD_JSON" ]; then
        image=$(jq -r '.build.image // empty' "$BUILD_JSON")
    else
        continue
    fi

    [ -z "$image" ] && continue

    # Clean architecture prefix from image
    cleaned_image="${image/\{arch\}/amd64}"
    cleaned_image="${cleaned_image/#ghcr.io\//}"
    cleaned_image="${cleaned_image/#docker.io\//}"

    # Get current version
    current_version=$(jq -r '.version' "$CONFIG_JSON")

    # Get latest tag from registry
    latest_version=$(get_latest_tag "$cleaned_image")

    if [ -z "$latest_version" ]; then
        log "${YELLOW}⚠️  Could not fetch tags for $cleaned_image${NC}"
        NOT_UPDATED_ADDONS+=("$ADDON_NAME")
        continue
    fi

    if compare_versions "$current_version" "$latest_version"; then
        log "${GREEN}✅ $ADDON_NAME needs update: $current_version → $latest_version${NC}"
        UPDATED_ADDONS+=("$ADDON_NAME: $current_version → $latest_version")

        if [ "$dry_run" != "true" ]; then
            jq --arg v "$latest_version" '.version = $v' "$CONFIG_JSON" > "${CONFIG_JSON}.tmp" && mv "${CONFIG_JSON}.tmp" "$CONFIG_JSON"
            echo "- $latest_version: Updated to match upstream tag" >> "${addon_dir}${CHANGELOG_FILE}"
            git add "$CONFIG_JSON" "${addon_dir}${CHANGELOG_FILE}" || true
        fi
    else
        log "${CYAN}⏩ $ADDON_NAME is already up to date ($current_version)${NC}"
        NOT_UPDATED_ADDONS+=("$ADDON_NAME")
    fi
done

# ========================================
# COMMIT & PUSH
# ========================================

if [ "$dry_run" != "true" ] && [ "${#UPDATED_ADDONS[@]}" -gt 0 ]; then
    COMMIT_MSG="🔄 Updated: ${UPDATED_ADDONS[*]}"
    git commit -am "$COMMIT_MSG" || true
    git push || true
    log "${GREEN}🚀 Changes pushed to GitHub.${NC}"
fi

# ========================================
# NOTIFY
# ========================================

summary_title="Add-on Update Report"
summary_msg=""

if [ "${#UPDATED_ADDONS[@]}" -gt 0 ]; then
    summary_msg+="✅ *Updated:*\n"
    for item in "${UPDATED_ADDONS[@]}"; do
        summary_msg+="• $item\n"
    done
fi

if [ "${#NOT_UPDATED_ADDONS[@]}" -gt 0 ]; then
    summary_msg+="\n⏹️ *Not Updated:*\n"
    for item in "${NOT_UPDATED_ADDONS[@]}"; do
        summary_msg+="• $item\n"
    done
fi

send_notification "$summary_title" "$summary_msg"

log "${CYAN}🛑 Script completed. Exiting.${NC}"
exit 0
