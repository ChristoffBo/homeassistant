#!/bin/sh
set -e

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_CYAN="\033[0;36m"

CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
TZ=$(jq -r '.timezone' "$CONFIG_PATH")
export TZ

log() {
    local color="$1"
    local msg="$2"
    echo "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}${msg}${COLOR_RESET}"
}

summary=""
add_to_summary() {
    summary="${summary}\n$1"
}

# Load Git credentials
GIT_USER=$(jq -r '.gituser' "$CONFIG_PATH")
GIT_TOKEN=$(jq -r '.gittoken' "$CONFIG_PATH")
REPO_URL=$(jq -r '.repository' "$CONFIG_PATH")
NOTIFY_ENABLED=$(jq -r '.enable_notifications' "$CONFIG_PATH")
NOTIFY_URL=$(jq -r '.notification_url' "$CONFIG_PATH")
NOTIFY_TOKEN=$(jq -r '.notification_token' "$CONFIG_PATH")

# Clone or pull repo
if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_BLUE" "🔄 Cloning repository..."
    git clone "https://${GIT_TOKEN:+$GIT_TOKEN@}${REPO_URL#https://}" "$REPO_DIR" || {
        log "$COLOR_RED" "❌ Git clone failed"
        add_to_summary "❌ Git clone failed"
    }
else
    log "$COLOR_BLUE" "ℹ️ Repository already exists, pulling latest..."
    cd "$REPO_DIR" && git reset --hard && git pull
fi

cd "$REPO_DIR"

# Loop through all add-ons
for ADDON_DIR in */; do
    ADDON_NAME="${ADDON_DIR%/}"
    log "$COLOR_BLUE" "ℹ️ Checking $ADDON_NAME"

    IMAGE=""
    FILE_FOUND=""

    for FILE in "config.json" "updater.json" "build.json"; do
        FILE_PATH="$REPO_DIR/$ADDON_NAME/$FILE"
        if [ -f "$FILE_PATH" ]; then
            IMAGE=$(jq -r '.image // empty' "$FILE_PATH" 2>/dev/null || true)
            if [ -n "$IMAGE" ]; then
                FILE_FOUND="$FILE"
                break
            fi
        fi
    done

    if [ -z "$IMAGE" ]; then
        log "$COLOR_YELLOW" "⚠️ $ADDON_NAME has no image defined"
        add_to_summary "⚠️ $ADDON_NAME: no image"
        continue
    fi

    log "$COLOR_GREEN" "✅ Found image for $ADDON_NAME in $FILE_FOUND: $IMAGE"
    add_to_summary "✅ $ADDON_NAME: found image in $FILE_FOUND"
done

log "$COLOR_BLUE" "ℹ️ Done. Script ran once and exited."

# Send Gotify notification
if [ "$NOTIFY_ENABLED" = "true" ] && [ -n "$NOTIFY_URL" ] && [ -n "$NOTIFY_TOKEN" ]; then
    curl -s -X POST "$NOTIFY_URL/message"         -F "token=$NOTIFY_TOKEN"         -F "title=Add-on Updater Summary"         -F "message=🧩 Add-on check summary:\n$summary"         -F "priority=5" > /dev/null 2>&1 || log "$COLOR_YELLOW" "⚠️ Failed to send Gotify notification"
fi
