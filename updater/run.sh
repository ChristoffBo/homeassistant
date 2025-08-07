#!/bin/bash
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
COLOR_BLUE="\033[0;34m"
COLOR_DARK_BLUE="\033[0;94m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# ======================
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS
declare -a SKIP_LIST=()

safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]][[:alnum:].:_-]*$' || echo "unknown"
}

read_config() {
  TZ=$(jq -er '.timezone // "UTC"' "$CONFIG_PATH" 2>/dev/null || echo "")
  export TZ

  DRY_RUN=$(jq -er '.dry_run // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  DEBUG=$(jq -er '.debug // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  SKIP_PUSH=$(jq -er '.skip_push // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  SKIP_LIST=($(jq -er '.skip_addons[]?' "$CONFIG_PATH" 2>/dev/null || echo ""))

  NOTIFY_ENABLED=$(jq -er '.enable_notifications // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SERVICE=$(jq -er '.notification_service // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_URL=$(jq -er '.notification_url // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TOKEN=$(jq -er '.notification_token // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TO=$(jq -er '.notification_to // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SUCCESS=$(jq -er '.notify_on_success // false' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_ERROR=$(jq -er '.notify_on_error // true' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_UPDATES=$(jq -er '.notify_on_updates // true' "$CONFIG_PATH" 2>/dev/null || echo "")

  GIT_PROVIDER=$(jq -er '.git_provider // "github"' "$CONFIG_PATH" 2>/dev/null || echo "github")

  if [ "$GIT_PROVIDER" = "gitea" ]; then
    GIT_REPO=$(jq -er '.gitea_repository' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_USER=$(jq -er '.gitea_username' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_TOKEN=$(jq -er '.gitea_token' "$CONFIG_PATH" 2>/dev/null || echo "")
  else
    GIT_REPO=$(jq -er '.github_repository' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_USER=$(jq -er '.github_username' "$CONFIG_PATH" 2>/dev/null || echo "")
    GIT_TOKEN=$(jq -er '.github_token' "$CONFIG_PATH" 2>/dev/null || echo "")
  fi

  GIT_AUTH_REPO="$GIT_REPO"
  if [ -n "$GIT_USER" ] && [ -n "$GIT_TOKEN" ]; then
    GIT_AUTH_REPO="${GIT_REPO/https:\/\//https://$GIT_USER:$GIT_TOKEN@}"
  fi
}

log() {
  local color="$1"; shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

notify() {
  local title="$1"
  local message="$2"
  local priority="${3:-0}"

  [ "$NOTIFY_ENABLED" != "true" ] && return
  case "$priority" in
    0) [ "$NOTIFY_SUCCESS" != "true" ] && return ;;
    3) [ "$NOTIFY_UPDATES" != "true" ] && return ;;
    5) [ "$NOTIFY_ERROR" != "true" ] && return ;;
  esac

  if [ "$NOTIFY_SERVICE" = "gotify" ]; then
    local payload
    payload=$(jq -n --arg t "$title" --arg m "$message" --argjson p "$priority" '{title: $t, message: $m, priority: $p}')
    curl -s -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" -H "Content-Type: application/json" -d "$payload" > /dev/null || log "$COLOR_RED" "❌ Gotify notification failed"
  fi
}

# [ ... rest of your unchanged code here including get_latest_tag, update_addon ... ]

commit_and_push() {
  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "Add-on Updater"

  # Handle unstaged changes before rebase
  if ! git diff --quiet || ! git diff --cached --quiet; then
    log "$COLOR_YELLOW" "📦 Unstaged changes detected — stashing before rebase"
    git stash
    STASHED=true
  fi

  git pull --rebase

  if [ "$STASHED" = "true" ]; then
    git stash pop || log "$COLOR_RED" "⚠️ Failed to apply stashed changes after rebase"
  fi

  if [ -n "$(git status --porcelain)" ]; then
    git add . && git commit -m "🔄 Updated add-on versions" || return
    [ "$SKIP_PUSH" = "true" ] && return
    git push "$GIT_AUTH_REPO" main || log "$COLOR_RED" "❌ Git push failed"
  else
    log "$COLOR_CYAN" "ℹ️ No changes to commit"
  fi
}

main() {
  echo "" > "$LOG_FILE"
  read_config
  log "$COLOR_BLUE" "ℹ️ Starting Home Assistant Add-on Updater"

  [ -d "$REPO_DIR" ] && rm -rf "$REPO_DIR"

  git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" || {
    log "$COLOR_RED" "❌ Git clone failed"
    notify "Updater Error" "Git clone failed" 5
    exit 1
  }

  for path in "$REPO_DIR"/*; do
    [ -d "$path" ] && update_addon "$path"
  done

  commit_and_push

  local summary="📦 Add-on Update Summary
"
  summary+="🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')

"

  for path in "$REPO_DIR"/*; do
    [ ! -d "$path" ] && continue
    local name=$(basename "$path")
    local status=""

    if [ -n "${UPDATED_ADDONS[$name]}" ]; then
      status="🔄 ${UPDATED_ADDONS[$name]}"
    elif [ -n "${UNCHANGED_ADDONS[$name]}" ]; then
      status="✅ ${UNCHANGED_ADDONS[$name]}"
    else
      status="⏭️ Skipped"
    fi

    summary+="$name: $status
"
  done

  [ "$DRY_RUN" = "true" ] && summary+="
🔁 DRY RUN MODE ENABLED"
  [ "$STASHED" = "true" ] && summary+="
📦 Unstaged changes were stashed and reapplied"

  notify "Add-on Updater" "$summary" 3
  log "$COLOR_BLUE" "ℹ️ Update process complete."
}

main