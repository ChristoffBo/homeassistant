#!/bin/sh
set -e

# ================
# CONFIGURATION
# ================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

# ================
# COLORS
# ================
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
BLUE="\033[0;34m"
CYAN="\033[0;36m"
PURPLE="\033[0;35m"
NC="\033[0m"

# ================
# GLOBALS
# ================
UPDATED=""
UNCHANGED=""
SKIPPED=""
DRY_RUN=false

log() {
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') $1$2${NC}" | tee -a "$LOG_FILE"
}

notify_gotify() {
  TITLE="$1"
  MESSAGE="$2"
  PRIORITY="${3:-0}"

  if [ "$NOTIFY_ENABLED" = true ] && [ "$NOTIFY_SERVICE" = "gotify" ]; then
    curl -s -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"${TITLE}\",\"message\":\"${MESSAGE}\",\"priority\":${PRIORITY}}" > /dev/null
  fi
}

load_config() {
  GITHUB_REPO=$(jq -r '.repository' "$CONFIG_PATH")
  GITHUB_USER=$(jq -r '.gituser' "$CONFIG_PATH")
  GITHUB_TOKEN=$(jq -r '.gittoken' "$CONFIG_PATH")
  TZ=$(jq -r '.timezone' "$CONFIG_PATH")
  export TZ

  DRY_RUN=$(jq -r '.dry_run' "$CONFIG_PATH")
  SKIP_PUSH=$(jq -r '.skip_push' "$CONFIG_PATH")
  DEBUG=$(jq -r '.debug' "$CONFIG_PATH")

  NOTIFY_ENABLED=$(jq -r '.enable_notifications' "$CONFIG_PATH")
  NOTIFY_SERVICE=$(jq -r '.notification_service' "$CONFIG_PATH")
  NOTIFY_URL=$(jq -r '.notification_url' "$CONFIG_PATH")
  NOTIFY_TOKEN=$(jq -r '.notification_token' "$CONFIG_PATH")
  NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success' "$CONFIG_PATH")
  NOTIFY_ON_ERROR=$(jq -r '.notify_on_error' "$CONFIG_PATH")
  NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates' "$CONFIG_PATH")
}

clone_repo() {
  if [ -z "$GITHUB_REPO" ]; then
    log "$RED" "❌ GitHub repository is not set."
    exit 1
  fi

  AUTH_REPO="$GITHUB_REPO"
  if [ -n "$GITHUB_TOKEN" ]; then
    AUTH_REPO="${GITHUB_REPO/https:\/\//https:\/\/$GITHUB_USER:$GITHUB_TOKEN@}"
  fi

  rm -rf "$REPO_DIR"
  git clone --depth 1 "$AUTH_REPO" "$REPO_DIR" || {
    log "$RED" "❌ Git clone failed"
    notify_gotify "Updater Error" "Git clone failed" 5
    exit 1
  }
}

get_latest_tag() {
  IMAGE="$1"
  ARCH=$(uname -m)
  ARCH=${ARCH/x86_64/amd64}
  ARCH=${ARCH/aarch64/arm64}
  IMAGE="${IMAGE//\{arch\}/$ARCH}"
  NAME="${IMAGE%%:*}"

  echo "$(curl -s "https://hub.docker.com/v2/repositories/${NAME}/tags?page_size=100" | jq -r '.results[].name' | grep -E '^[vV]?[0-9]' | grep -v latest | sort -Vr | head -n1)"
}

check_addon() {
  ADDON="$1"
  NAME=$(basename "$ADDON")

  [ "$NAME" = "updater" ] && return

  CONFIG="$ADDON/config.json"
  VERSION=$(jq -r '.version' "$CONFIG")
  IMAGE=$(jq -r '.image // empty' "$CONFIG")

  [ -z "$IMAGE" ] && {
    log "$YELLOW" "⚠️ $NAME has no image defined"
    SKIPPED="$SKIPPED\n$NAME: No image"
    return
  }

  LATEST=$(get_latest_tag "$IMAGE")

  if [ -z "$LATEST" ]; then
    log "$YELLOW" "⚠️ $NAME has no valid tags"
    SKIPPED="$SKIPPED\n$NAME: No valid tags"
    return
  fi

  if [ "$VERSION" != "$LATEST" ]; then
    log "$GREEN" "🔄 $NAME update: $VERSION → $LATEST"

    UPDATED="$UPDATED\n$NAME: $VERSION → $LATEST"

    if [ "$DRY_RUN" = true ]; then
      log "$PURPLE" "💡 Dry-run: skipping real update"
      return
    fi

    jq --arg v "$LATEST" '.version = $v' "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"

    echo -e "## $LATEST\n- Updated from $VERSION to $LATEST\n" | cat - "$ADDON/CHANGELOG.md" 2>/dev/null > "$ADDON/CHANGELOG.tmp"
    mv "$ADDON/CHANGELOG.tmp" "$ADDON/CHANGELOG.md"
  else
    log "$CYAN" "✅ $NAME is up to date ($VERSION)"
    UNCHANGED="$UNCHANGED\n$NAME: $VERSION"
  fi
}

commit_push() {
  cd "$REPO_DIR" || exit
  git config user.email "updater@local"
  git config user.name "Add-on Updater"
  git add .
  CHANGES=$(git status --porcelain)
  [ -z "$CHANGES" ] && {
    log "$CYAN" "ℹ️ No changes to commit"
    return
  }

  git commit -m "🔄 Auto-update add-on versions"
  [ "$SKIP_PUSH" = false ] && git push || log "$YELLOW" "⚠️ Skip push enabled"
}

summary_notify() {
  SUMMARY="📦 Add-on Update Summary\n🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')\n"

  [ -n "$UPDATED" ] && SUMMARY="$SUMMARY\n🔄 Updated:\n$UPDATED"
  [ -n "$UNCHANGED" ] && SUMMARY="$SUMMARY\n✅ Unchanged:\n$UNCHANGED"
  [ -n "$SKIPPED" ] && SUMMARY="$SUMMARY\n⏭️ Skipped:\n$SKIPPED"

  [ "$DRY_RUN" = true ] && SUMMARY="$SUMMARY\n🔁 Dry-run mode active"

  notify_gotify "Add-on Updater" "$SUMMARY" 3
  log "$BLUE" "ℹ️ Done."
}

main() {
  echo "" > "$LOG_FILE"
  load_config
  log "$BLUE" "ℹ️ Starting Home Assistant Add-on Updater"

  clone_repo

  for ADDON in "$REPO_DIR"/*; do
    [ -d "$ADDON" ] && check_addon "$ADDON"
  done

  commit_push
  summary_notify
}

main
exit 0