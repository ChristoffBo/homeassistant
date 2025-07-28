#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# Notification variables
NOTIFICATION_ENABLED=false
NOTIFICATION_SERVICE=""
NOTIFICATION_CONFIG=""
NOTIFY_ON_SUCCESS=false
NOTIFY_ON_ERROR=true
NOTIFY_ON_UPDATES=true

# Clear log file on startup
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  # Only log important messages (errors, warnings, success messages)
  if [[ "$color" == "$COLOR_RED" || "$color" == "$COLOR_YELLOW" || "$color" == "$COLOR_GREEN" ]]; then
    echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
  fi
}

send_notification() {
  local title="$1"
  local message="$2"
  local priority="${3:-0}"  # Default priority is normal (0)
  
  if [ "$NOTIFICATION_ENABLED" = "false" ]; then
    return
  fi

  case "$NOTIFICATION_SERVICE" in
    "gotify")
      local gotify_url=$(echo "$NOTIFICATION_CONFIG" | jq -r '.url')
      local gotify_token=$(echo "$NOTIFICATION_CONFIG" | jq -r '.token')
      if [ -z "$gotify_url" ] || [ -z "$gotify_token" ]; then
        log "$COLOR_RED" "❌ Gotify configuration incomplete"
        return
      fi
      curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
        "$gotify_url/message?token=$gotify_token" >> "$LOG_FILE" 2>&1
      ;;
    "mailrise")
      local mailrise_url=$(echo "$NOTIFICATION_CONFIG" | jq -r '.url')
      local mailrise_to=$(echo "$NOTIFICATION_CONFIG" | jq -r '.to')
      if [ -z "$mailrise_url" ] || [ -z "$mailrise_to" ]; then
        log "$COLOR_RED" "❌ Mailrise configuration incomplete"
        return
      fi
      curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"to\":\"$mailrise_to\", \"subject\":\"$title\", \"body\":\"$message\"}" \
        "$mailrise_url" >> "$LOG_FILE" 2>&1
      ;;
    "apprise")
      local apprise_url=$(echo "$NOTIFICATION_CONFIG" | jq -r '.url')
      if [ -z "$apprise_url" ]; then
        log "$COLOR_RED" "❌ Apprise configuration incomplete"
        return
      fi
      apprise -vv -t "$title" -b "$message" "$apprise_url" >> "$LOG_FILE" 2>&1
      ;;
    *)
      log "$COLOR_YELLOW" "⚠️ Unknown notification service: $NOTIFICATION_SERVICE"
      ;;
  esac
}

# Check for lock file to prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
  log "$COLOR_RED" "⚠️ Another update process is already running. Exiting."
  exit 1
fi

# Create lock file
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Read configuration
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron // "0 */6 * * *"' "$CONFIG_PATH")
STARTUP_CRON=$(jq -r '.startup_cron // empty' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
MAX_LOG_LINES=$(jq -r '.max_log_lines // 1000' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")

# Read notification configuration
NOTIFICATION_ENABLED=$(jq -r '.notifications.enabled // false' "$CONFIG_PATH")
if [ "$NOTIFICATION_ENABLED" = "true" ]; then
  NOTIFICATION_SERVICE=$(jq -r '.notifications.service // ""' "$CONFIG_PATH")
  NOTIFICATION_CONFIG=$(jq -r '.notifications.config // ""' "$CONFIG_PATH")
  NOTIFY_ON_SUCCESS=$(jq -r '.notifications.on_success // false' "$CONFIG_PATH")
  NOTIFY_ON_ERROR=$(jq -r '.notifications.on_error // true' "$CONFIG_PATH")
  NOTIFY_ON_UPDATES=$(jq -r '.notifications.on_updates // true' "$CONFIG_PATH")
fi

# Set timezone
export TZ="$TIMEZONE"

# Rotate log file if it's too large
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt "$MAX_LOG_LINES" ]; then
  log "$COLOR_YELLOW" "📜 Log file too large, rotating..."
  tail -n "$MAX_LOG_LINES" "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#(https?://)#\1$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Function to check if current time matches cron schedule
should_run_from_cron() {
  local cron_schedule="$1"
  if [ -z "$cron_schedule" ]; then
    return 1
  fi

  local current_minute=$(date '+%M')
  local current_hour=$(date '+%H')
  local current_day=$(date '+%d')
  local current_month=$(date '+%m')
  local current_weekday=$(date '+%w') # 0-6 (0=Sunday)

  # Parse cron schedule (min hour day month weekday)
  local cron_minute=$(echo "$cron_schedule" | awk '{print $1}')
  local cron_hour=$(echo "$cron_schedule" | awk '{print $2}')
  local cron_day=$(echo "$cron_schedule" | awk '{print $3}')
  local cron_month=$(echo "$cron_schedule" | awk '{print $4}')
  local cron_weekday=$(echo "$cron_schedule" | awk '{print $5}')

  # Check if current time matches cron schedule
  if [[ "$cron_minute" != "*" && "$cron_minute" != "$current_minute" ]]; then
    return 1
  fi
  if [[ "$cron_hour" != "*" && "$cron_hour" != "$current_hour" ]]; then
    return 1
  fi
  if [[ "$cron_day" != "*" && "$cron_day" != "$current_day" ]]; then
    return 1
  fi
  if [[ "$cron_month" != "*" && "$cron_month" != "$current_month" ]]; then
    return 1
  fi
  if [[ "$cron_weekday" != "*" && "$cron_weekday" != "$current_weekday" ]]; then
    return 1
  fi

  return 0
}

# Rest of the script remains the same (clone_or_update_repo, get_latest_docker_tag, etc.)
# [Previous functions remain unchanged...]

# Main execution
log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
log "$COLOR_GREEN" "⚙️ Configuration:"
log "$COLOR_GREEN" "   - Dry run: $DRY_RUN"
log "$COLOR_GREEN" "   - Skip push: $SKIP_PUSH"
log "$COLOR_GREEN" "   - Check cron: $CHECK_CRON"
log "$COLOR_GREEN" "   - Startup cron: ${STARTUP_CRON:-none}"
if [ "$NOTIFICATION_ENABLED" = "true" ]; then
  log "$COLOR_GREEN" "🔔 Notifications: Enabled (Service: $NOTIFICATION_SERVICE)"
  log "$COLOR_GREEN" "   - Notify on success: $NOTIFY_ON_SUCCESS"
  log "$COLOR_GREEN" "   - Notify on error: $NOTIFY_ON_ERROR"
  log "$COLOR_GREEN" "   - Notify on updates: $NOTIFY_ON_UPDATES"
else
  log "$COLOR_GREEN" "🔔 Notifications: Disabled"
fi

# First run on startup
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check

# Main loop
log "$COLOR_GREEN" "⏳ Waiting for cron triggers..."
while true; do
  # Check if we should run based on startup cron
  if [ -n "$STARTUP_CRON" ] && should_run_from_cron "$STARTUP_CRON"; then
    log "$COLOR_BLUE" "⏰ Startup cron triggered ($STARTUP_CRON)"
    perform_update_check
  fi

  # Check if we should run based on regular check cron
  if should_run_from_cron "$CHECK_CRON"; then
    log "$COLOR_BLUE" "⏰ Check cron triggered ($CHECK_CRON)"
    perform_update_check
  fi

  sleep 60
done
