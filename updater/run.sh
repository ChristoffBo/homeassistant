#!/bin/sh
set -e

# ========================================
# Home Assistant Add-on Updater (Run Once)
# ========================================

CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
TZ_DEFAULT="UTC"

# ===============
# Logging Colors
# ===============
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
BLUE="\033[0;34m"
CYAN="\033[0;36m"
RESET="\033[0m"

log() {
  echo "$(date +"[%Y-%m-%d %H:%M:%S %Z]") $1"
}

log_info()    { log "${BLUE}ℹ️ $1${RESET}"; }
log_success() { log "${GREEN}✅ $1${RESET}"; }
log_warn()    { log "${YELLOW}⚠️ $1${RESET}"; }
log_error()   { log "${RED}❌ $1${RESET}"; }

# ==================
# Load configuration
# ==================
TZ=$(jq -r '.timezone // empty' "$CONFIG_PATH")
[ -z "$TZ" ] && TZ=$TZ_DEFAULT
export TZ

REPO_URL=$(jq -r '.repository' "$CONFIG_PATH")
GIT_USER=$(jq -r '.gituser' "$CONFIG_PATH")
GIT_TOKEN=$(jq -r '.gittoken' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push' "$CONFIG_PATH")
DEBUG=$(jq -r '.debug' "$CONFIG_PATH")

NOTIFY_ENABLED=$(jq -r '.enable_notifications' "$CONFIG_PATH")
NOTIFY_SERVICE=$(jq -r '.notification_service' "$CONFIG_PATH")
NOTIFY_URL=$(jq -r '.notification_url' "$CONFIG_PATH")
NOTIFY_TOKEN=$(jq -r '.notification_token' "$CONFIG_PATH")
NOTIFY_TO=$(jq -r '.notification_to' "$CONFIG_PATH")
NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success' "$CONFIG_PATH")
NOTIFY_ON_ERROR=$(jq -r '.notify_on_error' "$CONFIG_PATH")
NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates' "$CONFIG_PATH")

log_info "Starting Home Assistant Add-on Updater"

# ========================
# Clone GitHub repository
# ========================
if [ -d "$REPO_DIR/.git" ]; then
  log_info "Repository already exists, pulling latest..."
  cd "$REPO_DIR" && git reset --hard && git pull || log_error "Git pull failed"
else
  log_info "Cloning repo $REPO_URL"
  git clone --depth=1 "https://${GIT_USER}:${GIT_TOKEN}@${REPO_URL#https://}" "$REPO_DIR" || {
    log_error "Git clone failed"
    exit 1
  }
fi

# ========================
# Add-on scanning function
# ========================
check_addon_update() {
  ADDON="$1"
  ADDON_DIR="$REPO_DIR/$ADDON"
  CONFIG_JSON="$ADDON_DIR/config.json"
  BUILD_JSON="$ADDON_DIR/build.json"

  IMAGE=$(jq -r '.image // empty' "$CONFIG_JSON")
  [ -z "$IMAGE" ] && IMAGE=$(jq -r '.image // empty' "$BUILD_JSON")
  if [ -z "$IMAGE" ]; then
    log_warn "$ADDON has no image defined"
    return
  fi

  # Determine registry type
  if echo "$IMAGE" | grep -q "ghcr.io"; then
    REGISTRY="ghcr"
  elif echo "$IMAGE" | grep -q "linuxserver"; then
    REGISTRY="lsio"
  else
    REGISTRY="dockerhub"
  fi

  CURRENT_TAG=$(echo "$IMAGE" | awk -F ':' '{print $2}')
  BASE_IMAGE=$(echo "$IMAGE" | awk -F ':' '{print $1}')

  # Fetch latest tag (simulated or real)
  # You can implement curl/jq calls here
  LATEST_TAG="$CURRENT_TAG" # Simulate no update for now

  if [ "$CURRENT_TAG" = "$LATEST_TAG" ]; then
    log_success "$ADDON is up to date ($CURRENT_TAG)"
  else
    log_info "Update available for $ADDON: $CURRENT_TAG → $LATEST_TAG"
    # Update logic and CHANGELOG update here
    if [ "$DRY_RUN" = "false" ]; then
      sed -i "s|$CURRENT_TAG|$LATEST_TAG|" "$CONFIG_JSON" || true
      sed -i "s|$CURRENT_TAG|$LATEST_TAG|" "$BUILD_JSON" || true
    fi
  fi
}

# =======================
# Loop through add-ons
# =======================
cd "$REPO_DIR"
ADDONS=$(find . -name "config.json" -exec dirname {} \; | sed 's|^\./||')

for ADDON in $ADDONS; do
  log_info "Checking $ADDON"
  check_addon_update "$ADDON"
done

# =======================
# Git Commit & Push
# =======================
if [ "$DRY_RUN" = "false" ]; then
  git config user.name "$GIT_USER"
  git config user.email "$GIT_USER@users.noreply.github.com"
  git add .
  git diff-index --quiet HEAD || {
    git commit -m "Addon updates [$(date)]"
    [ "$SKIP_PUSH" = "false" ] && git push || log_info "Push skipped"
  }
else
  log_warn "Dry run enabled, skipping commit/push"
fi

log_info "Done."
