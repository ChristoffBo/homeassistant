#!/bin/sh
set -e

# Colors for logs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

LOG() {
    level=$1
    shift
    case "$level" in
        INFO) color=$CYAN ;;
        WARN) color=$YELLOW ;;
        ERROR) color=$RED ;;
        DRYRUN) color=$MAGENTA ;;
        *) color=$NC ;;
    esac
    printf "%b[%s] %s%b\n" "$color" "$level" "$*" "$NC"
}

# Load config.json into shell variables
CONFIG_FILE="/data/options.json"

get_json_value() {
    jq -r "$1" "$CONFIG_FILE" 2>/dev/null || echo ""
}

GITUSER=$(get_json_value '.gituser')
GITMAIL=$(get_json_value '.gitmail')
GITAPI=$(get_json_value '.gitapi')
REPOSITORY=$(get_json_value '.repository')
VERBOSE=$(get_json_value '.verbose')
DRY_RUN=$(get_json_value '.dry_run')
ENABLE_NOTIFICATIONS=$(get_json_value '.enable_notifications')

# Repo folder path
REPO_DIR="/data/$(basename "$REPOSITORY")"

LOG INFO "===== ADDON UPDATER STARTED ====="
if [ "$DRY_RUN" = "true" ]; then
    LOG DRYRUN "Dry run mode enabled. No changes will be pushed."
else
    LOG INFO "Live mode enabled. Changes will be pushed."
fi

LOG INFO "Repository: $REPOSITORY"

# Configure git user
git config --global user.name "$GITUSER"
if [ "$GITMAIL" != "null" ] && [ -n "$GITMAIL" ]; then
    git config --global user.email "$GITMAIL"
fi

# Clone or update repo with token auth
if [ ! -d "$REPO_DIR" ]; then
    LOG INFO "Cloning repository $REPOSITORY (shallow)..."
    git clone --depth=1 "https://${GITAPI}@github.com/${REPOSITORY}.git" "$REPO_DIR" || {
        LOG ERROR "Failed to clone repository"
        exit 1
    }
else
    LOG INFO "Updating repository $REPOSITORY..."
    cd "$REPO_DIR" || exit 1
    git pull --rebase origin main || {
        LOG WARN "Git pull failed, attempting hard reset..."
        git reset --hard origin/main || {
            LOG ERROR "Hard reset failed, recloning repository..."
            cd /data || exit 1
            rm -rf "$REPO_DIR"
            git clone --depth=1 "https://${GITAPI}@github.com/${REPOSITORY}.git" "$REPO_DIR" || {
                LOG ERROR "Failed to clone repository"
                exit 1
            }
        }
    }
fi

cd "$REPO_DIR" || exit 1

# Loop through addons and check updates...
for addon in */; do
    [ -f "${addon}updater.json" ] || {
        LOG WARN "Skipping $addon - no updater.json found"
        continue
    }
    SLUG=$(basename "$addon")
    CURRENT=$(jq -r '.upstream_version' "${addon}updater.json")

    # Logic to get the latest version from dockerhub or GitHub releases goes here
    # For example, simulate fetching latest version:
    LATEST="v1.0.0"  # Replace with actual logic

    if [ "$CURRENT" != "$LATEST" ]; then
        LOG INFO "Addon $SLUG update available: $CURRENT -> $LATEST"

        if [ "$DRY_RUN" = "true" ]; then
            LOG DRYRUN "Dry run: would update $SLUG to $LATEST"
        else
            # Update files with new version
            # git add/commit/push logic here

            LOG INFO "Updating $SLUG to $LATEST"

            # Commit changes
            git add "$addon"
            git commit -m "Update $SLUG to $LATEST" || true
            git push "https://${GITAPI}@github.com/${REPOSITORY}.git" main
        fi
    else
        LOG INFO "Addon $SLUG is up-to-date ($CURRENT)"
    fi
done

LOG INFO "Addon update check complete."
