#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config
TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ

# Logging with color and timestamp
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  echo -e "[\033[90m$(date '+%Y-%m-%d %H:%M:%S %Z')\033[0m] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

send_notification() {
  local message="$1"
  local type=$(jq -r '.notifier.type' "$CONFIG_PATH")
  local url=$(jq -r '.notifier.url' "$CONFIG_PATH")
  local token=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")

  if [[ -z "$type" || -z "$url" ]]; then
    return
  fi

  case "$type" in
    gotify)
      curl -s -X POST "$url/message" \
        -H "X-Gotify-Key: $token" \
        -F "title=Addon Updater" \
        -F "message=$message" \
        -F "priority=5" > /dev/null || true
      ;;
    mailrise)
      curl -s -X POST "$url" -H "Content-Type: text/plain" --data "$message" > /dev/null || true
      ;;
    apprise)
      curl -s "$url" -d "$message" > /dev/null || true
      ;;
    *)
      log "$COLOR_RED" "❌ Unknown notifier type: $type"
      ;;
  esac
}

# Schedule cron from GUI option
CRON_SCHEDULE=$(jq -r '.cron // "0 4 * * *"' "$CONFIG_PATH")

# Write cron job
CRON_FILE="/etc/crontabs/root"
echo "$CRON_SCHEDULE /bin/bash /run.sh >> $LOG_FILE 2>&1" > "$CRON_FILE"
log "$COLOR_BLUE" "📅 Cron schedule set to: $CRON_SCHEDULE"

# Start cron service if not running
crond -f &
log "$COLOR_BLUE" "🕒 Cron service started"

# Main update logic (wrapped in function for cron to reuse)
update_addons() {
  cd "$REPO_DIR"
  UPDATED=0

  for addon in */config.json; do
    ADDON_DIR=$(dirname "$addon")
    NAME=$(jq -r '.name' "$addon")
    IMAGE=$(jq -r '.image' "$REPO_DIR/$addon")
    CURRENT_VERSION=$(jq -r '.version' "$REPO_DIR/$addon")

    log "$COLOR_PURPLE" "\n🧩 Addon: $ADDON_DIR"
    log "$COLOR_BLUE" "🔢 Current version: $CURRENT_VERSION"
    log "$COLOR_BLUE" "📦 Image: $IMAGE"

    REPO="${IMAGE%:*}"
    TAG="${IMAGE##*:}"

    if [[ "$TAG" == "latest" || "$TAG" == *"latest"* ]]; then
      log "$COLOR_YELLOW" "⚠️ Skipping: 'latest' tag is not supported."
      continue
    fi

    NORMALIZED_TAG=$(echo "$TAG" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

    if [[ "$REPO" == *"linuxserver"* ]]; then
      API_URL="https://hub.docker.com/v2/repositories/${REPO//lscr.io\//linuxserver\/}/tags?page_size=100"
    else
      API_URL="https://hub.docker.com/v2/repositories/${REPO//docker.io\//}/tags?page_size=100"
    fi

    TAGS=$(curl -s "$API_URL" | jq -r '.results[].name' | grep -v 'latest' || true)
    LATEST_TAG=$(echo "$TAGS" | grep -v 'latest' | grep -v 'rc' | sort -Vr | head -n1)

    if [[ -z "$LATEST_TAG" ]]; then
      log "$COLOR_RED" "❌ Could not fetch tags for $REPO"
      continue
    fi

    log "$COLOR_GREEN" "🚀 Latest version: $LATEST_TAG"
    log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

    if [[ "$NORMALIZED_TAG" != "$LATEST_TAG" ]]; then
      log "$COLOR_YELLOW" "⬆️  Updating $ADDON_DIR from $TAG to $LATEST_TAG"

      jq --arg ver "$LATEST_TAG" '.version = $ver' "$REPO_DIR/$ADDON_DIR/build.json" > tmp.$$.json && mv tmp.$$.json "$REPO_DIR/$ADDON_DIR/build.json"

      if [[ -f "$REPO_DIR/$ADDON_DIR/updater.json" ]]; then
        jq --arg ver "$LATEST_TAG" '.version = $ver' "$REPO_DIR/$ADDON_DIR/updater.json" > tmp.$$.json && mv tmp.$$.json "$REPO_DIR/$ADDON_DIR/updater.json"
      fi

      jq --arg ver "$LATEST_TAG" '.version = $ver' "$REPO_DIR/$ADDON_DIR/config.json" > tmp.$$.json && mv tmp.$$.json "$REPO_DIR/$ADDON_DIR/config.json"

      CHANGELOG="$REPO_DIR/$ADDON_DIR/CHANGELOG.md"
      if [[ ! -f "$CHANGELOG" ]]; then
        echo "# Changelog" > "$CHANGELOG"
      fi
      echo -e "\n## $LATEST_TAG - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$TAG\` to \`$LATEST_TAG\`" >> "$CHANGELOG"
      log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $ADDON_DIR"

      UPDATED=1
    else
      log "$COLOR_GREEN" "✔️ $ADDON_DIR is already up to date ($TAG)"
    fi

    log "$COLOR_BLUE" "----------------------------"
  done

  if [[ $UPDATED -eq 1 ]]; then
    send_notification "📦 One or more add-ons have been updated in Home Assistant."
  else
    log "$COLOR_GREEN" "✅ No updates needed."
  fi
}

# If run directly (not by cron), execute once now
if [[ "$1" != "cron" ]]; then
  update_addons
fi

# Keep container alive
sleep infinity
