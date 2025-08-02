#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
MAX_LOG_FILES=5
MAX_LOG_LINES=1000

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
# NOTIFICATION SETTINGS
# ======================
declare -A NOTIFICATION_SETTINGS=(
    [enabled]=false
    [service]=""
    [url]=""
    [token]=""
    [to]=""
    [on_success]=false
    [on_error]=true
    [on_updates]=true
)

# ======================
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS
declare -A FAILED_ADDONS
DRY_RUN=false
DEBUG=false
SKIP_PUSH=false
TIMEZONE="UTC"
GIT_USERNAME=""
GIT_TOKEN=""
GIT_REPO=""
CRON=""
NOTIFY_SUMMARY=""
NOW=""
TZ_OFFSET=""
UPDATES_FOUND=false

# ======================
# LOGGING FUNCTIONS
# ======================
log() {
  local color="$1"
  local message="$2"
  local ts="[$(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')]"
  echo -e "${ts} ${color}${message}${COLOR_RESET}" | tee -a "$LOG_FILE"
}

log_info() { log "$COLOR_BLUE" "ℹ️ $1"; }
log_success() { log "$COLOR_GREEN" "✅ $1"; }
log_warn() { log "$COLOR_YELLOW" "⚠️ $1"; }
log_error() { log "$COLOR_RED" "❌ $1"; }
log_debug() { $DEBUG && log "$COLOR_PURPLE" "🐛 $1"; }

# ======================
# CONFIG LOADER
# ======================
load_config() {
  if [[ ! -f "$CONFIG_PATH" ]]; then
    log_error "Missing config at $CONFIG_PATH"
    exit 1
  fi

  GIT_REPO=$(jq -r '.repository // empty' "$CONFIG_PATH")
  GIT_USERNAME=$(jq -r '.gituser // empty' "$CONFIG_PATH")
  GIT_TOKEN=$(jq -r '.gittoken // empty' "$CONFIG_PATH")
  TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
  DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
  SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
  DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
  CRON=$(jq -r '.cron // empty' "$CONFIG_PATH")

  NOTIFICATION_SETTINGS[enabled]=$(jq -r '.enable_notifications // false' "$CONFIG_PATH")
  NOTIFICATION_SETTINGS[service]=$(jq -r '.notification_service // empty' "$CONFIG_PATH")
  NOTIFICATION_SETTINGS[url]=$(jq -r '.notification_url // empty' "$CONFIG_PATH")
  NOTIFICATION_SETTINGS[token]=$(jq -r '.notification_token // empty' "$CONFIG_PATH")
  NOTIFICATION_SETTINGS[to]=$(jq -r '.notification_to // empty' "$CONFIG_PATH")
  NOTIFICATION_SETTINGS[on_success]=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
  NOTIFICATION_SETTINGS[on_error]=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
  NOTIFICATION_SETTINGS[on_updates]=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")

  log_info "Configuration loaded"
}

# ======================
# NOTIFICATION LOGIC
# ======================
notify() {
  local message="$1"
  [[ "${NOTIFICATION_SETTINGS[enabled]}" != "true" ]] && return

  case "${NOTIFICATION_SETTINGS[service]}" in
    gotify)
      curl -s -X POST "${NOTIFICATION_SETTINGS[url]}/message" \
        -H "X-Gotify-Key: ${NOTIFICATION_SETTINGS[token]}" \
        -H 'Content-Type: application/json' \
        -d "{\"title\":\"📦 Home Assistant Add-on Update Summary\",\"message\":\"${message}\",\"priority\":5}" >/dev/null
      ;;
    apprise|mailrise)
      curl -s -X POST "${NOTIFICATION_SETTINGS[url]}" \
        -H 'Content-Type: application/json' \
        -d "{\"token\":\"${NOTIFICATION_SETTINGS[token]}\",\"to\":\"${NOTIFICATION_SETTINGS[to]}\",\"title\":\"📦 Home Assistant Add-on Update Summary\",\"message\":\"${message}\"}" >/dev/null
      ;;
  esac
}

format_summary() {
  local summary=""
  summary+="🕒 $(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')\n\n🧩 Add-on Results:"
  for addon in "${!UPDATED_ADDONS[@]}"; do
    summary+="\n• ${addon}: ${UPDATED_ADDONS[$addon]}"
  done
  for addon in "${!FAILED_ADDONS[@]}"; do
    summary+="\n• ${addon}: ❓ ${FAILED_ADDONS[$addon]}"
  done
  [[ "$DRY_RUN" == "true" ]] && summary+="\n\n💡 Dry run enabled — no changes were made"
  echo -e "$summary"
}

# ======================
# MOCK UPDATE CHECKER (replace with real logic)
# ======================
check_addon() {
  local addon="$1"

  # Example: skip Heimdall due to JSON error
  if [[ "$addon" == "heimdall" ]]; then
    log_warn "$addon skipped due to known JSON error"
    FAILED_ADDONS["$addon"]="Skipped due to JSON error"
    return
  fi

  log_info "🔍 Checking $addon"

  # Simulate version check
  if [[ "$addon" == "gotify" ]]; then
    UPDATED_ADDONS["$addon"]="🔄 Updated from 2.6.2 → 2.6.3"
    UPDATES_FOUND=true
  else
    UPDATED_ADDONS["$addon"]="⚠️ Up to date (1.0.0)"
  fi
}

# ======================
# MAIN SCRIPT
# ======================
main() {
  load_config

  log_info "=================================="
  log_info "Starting Home Assistant Updater"
  [[ "$DRY_RUN" == "true" ]] && log_warn "Running in DRY RUN mode — no changes will be saved"
  log_info "=================================="

  local addons=(gotify heimdall gitea metube)
  for addon in "${addons[@]}"; do
    check_addon "$addon"
  done

  NOTIFY_SUMMARY=$(format_summary)
  notify "$NOTIFY_SUMMARY"

  log_info "=================================="
  log_success "Update check completed"
  log_info "=================================="
}

main