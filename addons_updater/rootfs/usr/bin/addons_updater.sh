#!/bin/sh
set -e

START_TIME=$(date +%s)
TZ="${TZ:-Africa/Johannesburg}"
export TZ

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Notification Settings
NOTIFY_GOTIFY="${GOTIFY_URL:-}"
GOTIFY_TOKEN="${GOTIFY_TOKEN:-}"
DRYRUN="${DRYRUN:-true}"
ADDON_DIR="/addons"
REPO_URL="https://github.com/ChristoffBo/homeassistant"

log()    { echo -e "${BLUE}[INFO]${NC} $1"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()  { echo -e "${RED}[ERROR]${NC} $1"; }
note()   { echo -e "${CYAN}[DRYRUN]${NC} $1"; }
success(){ echo -e "${GREEN}[OK]${NC} $1"; }

# Banner
echo
[ "$DRYRUN" = "true" ] && note "===== ADDON UPDATER STARTED (Dry Run) =====" || success "===== ADDON UPDATER STARTED (Live Mode) ====="
echo " Dry run mode: $DRYRUN"
echo " Notifications: $( [ -n "$NOTIFY_GOTIFY" ] && echo Enabled || echo Disabled )"
echo "-----------------------------------------------------------"

# Git sync
if [ -d "$ADDON_DIR/.git" ]; then
    log "Repository exists, updating..."
    git -C "$ADDON_DIR" pull --quiet
else
    log "Cloning repository..."
    git clone --depth=1 "$REPO_URL" "$ADDON_DIR"
fi

cd "$ADDON_DIR"

# Detect latest Docker tag
get_latest_tag() {
    IMAGE="$1"
    PROVIDER="$2"
    case "$PROVIDER" in
        dockerhub)
            curl -s "https://hub.docker.com/v2/repositories/${IMAGE}/tags/?page_size=50" |
                jq -r '.results[].name' |
                grep -v latest |
                sort -Vr | head -n1
            ;;
        linuxserver)
            curl -s "https://hub.docker.com/v2/repositories/linuxserver/${IMAGE}/tags/?page_size=50" |
                jq -r '.results[].name' |
                grep -v latest |
                sort -Vr | head -n1
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

# Process add-ons
UPDATES=""
for addon in $(ls -1 "$ADDON_DIR" | grep -vE '\.git|README|LICENSE'); do
    ADDON_PATH="$ADDON_DIR/$addon"
    CONFIG="$ADDON_PATH/config.json"
    BUILD="$ADDON_PATH/build.json"
    META="$ADDON_PATH/updater.json"

    [ ! -f "$META" ] && warn "$addon: Missing updater.json, skipping" && continue

    IMAGE=$(jq -r .image "$META")
    PROVIDER=$(jq -r .provider "$META")
    CURRENT=$(jq -r .version "$BUILD" 2>/dev/null || echo "unknown")

    # Skip if image or provider missing
    [ "$IMAGE" = "null" ] || [ "$PROVIDER" = "null" ] && warn "$addon: Invalid metadata" && continue

    # Get latest version
    LATEST=$(get_latest_tag "$IMAGE" "$PROVIDER")

    if [ "$LATEST" = "unknown" ]; then
        warn "$addon: Failed to get latest tag"
        continue
    fi

    if [ "$CURRENT" = "$LATEST" ]; then
        log "$addon: No update needed, version is $CURRENT"
        continue
    fi

    # Perform update or simulate
    if [ "$DRYRUN" = "true" ]; then
        note "$addon: Update simulated from $CURRENT to $LATEST"
    else
        success "$addon: Updating from $CURRENT to $LATEST"
        jq --arg v "$LATEST" '.version = $v' "$BUILD" > "$BUILD.tmp" && mv "$BUILD.tmp" "$BUILD"

        # Update CHANGELOG
        CHANGELOG="$ADDON_PATH/CHANGELOG.md"
        [ ! -f "$CHANGELOG" ] && echo "# Changelog for $addon" > "$CHANGELOG"
        echo "- Updated to **$LATEST** from **$CURRENT** ($(date +'%Y-%m-%d %H:%M'))" >> "$CHANGELOG"

        # Git commit
        git add "$BUILD" "$CHANGELOG"
        git commit -m "$addon: Updated from $CURRENT to $LATEST" --quiet
    fi

    # Collect for notification
    UPDATES="$UPDATES\n$addon: $CURRENT ➜ $LATEST"
done

# Push changes if not dry run
if [ "$DRYRUN" != "true" ]; then
    git push --quiet
fi

# Gotify Notify
if [ -n "$NOTIFY_GOTIFY" ]; then
    if [ -n "$UPDATES" ]; then
        MSG="🟢 Add-on updates completed:\n$UPDATES"
    else
        MSG="ℹ️ No updates were needed."
    fi
    curl -s -X POST "$NOTIFY_GOTIFY/message" \
        -H "X-Gotify-Key: $GOTIFY_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"title": "Add-on Updater", "message": "'"$MSG"'", "priority": 5}' >/dev/null && log "Gotify notification sent."
fi

# Finish
ELAPSED=$(( $(date +%s) - START_TIME ))
[ "$DRYRUN" = "true" ] && note "===== ADDON UPDATER FINISHED in ${ELAPSED}s (Dry Run) =====" || success "===== ADDON UPDATER FINISHED in ${ELAPSED}s (Live Mode) ====="
