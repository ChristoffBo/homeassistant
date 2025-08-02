#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"

# ======================
# COLOR DEFINITIONS
# ======================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_RED="\033[0;31m"
COLOR_YELLOW="\033[1;33m"
COLOR_CYAN="\033[0;36m"

# ======================
# LOAD CONFIG
# ======================
GH_REPO=$(jq -r '.repo' "$CONFIG_PATH")
GH_USERNAME=$(jq -r '.username' "$CONFIG_PATH")
GH_TOKEN=$(jq -r '.token' "$CONFIG_PATH")
NOTIFY_ENABLED=$(jq -r '.notifications_enabled' "$CONFIG_PATH")
NOTIFY_SERVICE=$(jq -r '.notification_service' "$CONFIG_PATH")
NOTIFY_URL=$(jq -r '.notification_url' "$CONFIG_PATH")
NOTIFY_TOKEN=$(jq -r '.notification_token' "$CONFIG_PATH")

# ======================
# GOTIFY FUNCTION
# ======================
send_gotify() {
    TITLE="$1"
    MESSAGE="$2"
    curl -s -X POST "$NOTIFY_URL/message" \
        -F "token=$NOTIFY_TOKEN" \
        -F "title=$TITLE" \
        -F "message=$MESSAGE" \
        -F "priority=5" > /dev/null
}

# ======================
# LOG START
# ======================
echo -e "${COLOR_CYAN}Starting Home Assistant Add-on Updater...${COLOR_RESET}"
START_TIME=$(date +%s)

# ======================
# CLONE OR UPDATE REPO
# ======================
if [ ! -d "$REPO_DIR/.git" ]; then
    echo -e "${COLOR_YELLOW}Cloning repository...${COLOR_RESET}"
    git clone --depth 1 "https://$GH_USERNAME:$GH_TOKEN@${GH_REPO#https://}" "$REPO_DIR"
else
    echo -e "${COLOR_YELLOW}Pulling latest changes...${COLOR_RESET}"
    cd "$REPO_DIR" && git pull
fi

cd "$REPO_DIR"

# ======================
# INITIALIZE SUMMARY
# ======================
UPDATED_ADDONS=""
UNCHANGED_ADDONS=""

# ======================
# MAIN UPDATE LOOP
# ======================
for ADDON in */; do
    ADDON="${ADDON%/}"
    ADDON_DIR="$REPO_DIR/$ADDON"

    if [ ! -f "$ADDON_DIR/updater.json" ]; then
        echo -e "${COLOR_RED}Skipping $ADDON – missing updater.json${COLOR_RESET}"
        continue
    fi

    IMAGE=$(jq -r '.image' "$ADDON_DIR/updater.json")
    LASTVERSION=$(jq -r '.last_version' "$ADDON_DIR/updater.json")
    SLUG=$(jq -r '.slug' "$ADDON_DIR/config.json")

    if [[ "$IMAGE" == *"docker.io"* || "$IMAGE" == *"ghcr.io"* || "$IMAGE" == *"lscr.io"* ]]; then
        IMAGE_NO_REG="${IMAGE#*/}"
    else
        IMAGE_NO_REG="$IMAGE"
    fi

    # ======================
    # GET LATEST VERSION
    # ======================
    echo -e "${COLOR_CYAN}Checking $SLUG ($IMAGE)...${COLOR_RESET}"

    if [[ "$IMAGE" == *"ghcr.io"* ]]; then
        TAGS=$(curl -s -H "Authorization: Bearer $GH_TOKEN" "https://ghcr.io/v2/${IMAGE_NO_REG}/tags/list" | jq -r '.tags[]')
    else
        TAGS=$(curl -s "https://registry.hub.docker.com/v2/repositories/${IMAGE_NO_REG}/tags?page_size=100" | jq -r '.results[].name')
    fi

    # Filter versions (exclude latest, architecture tags)
    LATEST_TAG=$(echo "$TAGS" | grep -E '^[v]?[0-9]+(\.[0-9]+)*([-._]?[a-zA-Z0-9]*)?$' | grep -v 'latest' | sort -V | tail -1)

    if [ -z "$LATEST_TAG" ]; then
        echo -e "${COLOR_RED}No valid version tags found for $SLUG${COLOR_RESET}"
        continue
    fi

    if [ "$LASTVERSION" != "$LATEST_TAG" ]; then
        echo -e "${COLOR_GREEN}Update found: $LASTVERSION → $LATEST_TAG${COLOR_RESET}"

        # Replace in all files
        for FILE in "updater.json" "config.json" "build.json"; do
            FILE_PATH="$ADDON_DIR/$FILE"
            if [ -f "$FILE_PATH" ]; then
                sed -i "s/$LASTVERSION/$LATEST_TAG/g" "$FILE_PATH"
            fi
        done

        # Git commit
        cd "$REPO_DIR"
        git add "$ADDON_DIR"
        git commit -m "$SLUG updated: $LASTVERSION → $LATEST_TAG" > /dev/null || true

        UPDATED_ADDONS+="$SLUG: $LASTVERSION → $LATEST_TAG\n"
    else
        echo -e "${COLOR_YELLOW}No update for $SLUG ($LASTVERSION)${COLOR_RESET}"
        UNCHANGED_ADDONS+="$SLUG (current: $LASTVERSION)\n"
    fi
done

# ======================
# GIT PUSH
# ======================
if [ -n "$(git status --porcelain)" ]; then
    git push
fi

# ======================
# SEND NOTIFICATION
# ======================
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
SUMMARY_MSG="Home Assistant Add-on Update Summary\n\n"

if [ -n "$UPDATED_ADDONS" ]; then
    SUMMARY_MSG+="✅ Updated Add-ons:\n$UPDATED_ADDONS\n"
else
    SUMMARY_MSG+="✅ No updates were necessary.\n"
fi

if [ -n "$UNCHANGED_ADDONS" ]; then
    SUMMARY_MSG+="📦 Unchanged Add-ons:\n$UNCHANGED_ADDONS\n"
fi

SUMMARY_MSG+="⏱️ Duration: ${DURATION}s"

if [ "$NOTIFY_ENABLED" = "true" ] && [ "$NOTIFY_SERVICE" = "gotify" ]; then
    send_gotify "Add-on Updater Finished" "$SUMMARY_MSG"
fi

echo -e "${COLOR_CYAN}Update completed in $DURATION seconds.${COLOR_RESET}"
