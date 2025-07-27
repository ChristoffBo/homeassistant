#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "❌ ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
if [[ "$GITHUB_REPO" != *.git ]]; then
  GITHUB_REPO="${GITHUB_REPO}.git"
fi

GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")

CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")
if [ -z "$CHECK_CRON" ] || [ "$CHECK_CRON" == "null" ]; then
  log "$COLOR_RED" "❌ ERROR: 'check_cron' is not set in $CONFIG_PATH"
  exit 1
fi

LOG_FILE="/data/updater.log"
: > "$LOG_FILE"

LAST_RUN_FILE="/data/last_run_date.txt"

# Requires 'crontab' and 'date' commands to be available.
# Checks if current time matches the cron schedule:
matches_cron() {
  local cron_expr="$1"
  local now_min=$(date +'%M')
  local now_hour=$(date +'%H')
  local now_day=$(date +'%d')
  local now_month=$(date +'%m')
  local now_dow=$(date +'%w')

  # We'll use 'crontab' tool's built-in check with help of 'croniter' or minimal implementation
  # but since minimal bash, let's use 'crontab' tool for matching time. 
  # Unfortunately, shell lacks native cron expression parser,
  # so we use a workaround: echo the cron line and check with 'cronnext' or external tools (if available).
  #
  # Since that's complex, a simple workaround is to use 'grep' on date +%M %H %d %m %w
  # For better accuracy, you can install 'croniter' Python package or similar tools.

  # For now, to keep things simple and working, let's only support cron in form "MIN HOUR * * *"
  # i.e. only minute and hour fields matter for daily scheduling.

  local cron_min=$(echo "$cron_expr" | awk '{print $1}')
  local cron_hour=$(echo "$cron_expr" | awk '{print $2}')

  # Support * wildcard:
  if [[ "$cron_min" == "*" ]]; then
    cron_min="$now_min"
  fi
  if [[ "$cron_hour" == "*" ]]; then
    cron_hour="$now_hour"
  fi

  if [[ "$cron_min" == "$now_min" && "$cron_hour" == "$now_hour" ]]; then
    return 0
  fi
  return 1
}

clone_or_update_repo() {
  log "$COLOR_BLUE" "📥 Pulling latest changes from $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "📂 Repository not found locally. Cloning..."
    git clone "$GITHUB_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository cloned successfully."
  else
    log "$COLOR_BLUE" "🔄 Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull origin main >> "$LOG_FILE" 2>&1
    log "$COLOR_GREEN" "✅ Repository updated."
  fi
}

# (Other functions remain unchanged: fetch_latest_dockerhub_tag, fetch_latest_linuxserver_tag, fetch_latest_ghcr_tag, get_latest_docker_tag, update_addon_if_needed, perform_update_check)

# Include your unchanged functions here (or source them)

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updated=0
  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path" && updated=$((updated+1))
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "Automatic update: bump addon versions" >> "$LOG_FILE" 2>&1 || true

    export GIT_ASKPASS=$(mktemp)
    chmod +x "$GIT_ASKPASS"
    cat <<EOF > "$GIT_ASKPASS"
#!/bin/sh
case "\$1" in
Username*) echo "$GITHUB_USERNAME" ;;
Password*) echo "$GITHUB_TOKEN" ;;
esac
EOF

    if git push origin main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "🚀 Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed. Check your authentication and remote URL."
    fi

    rm -f "$GIT_ASKPASS"
    unset GIT_ASKPASS
  else
    log "$COLOR_BLUE" "ℹ️ No changes to commit."
  fi
}

log "$COLOR_GREEN" "🚀 HomeAssistant Add-on Updater started at $(date '+%d-%m-%Y %H:%M')"
perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

while true; do
  if matches_cron "$CHECK_CRON"; then
    TODAY=$(date +%Y-%m-%d)
    LAST_RUN=""
    if [ -f "$LAST_RUN_FILE" ]; then
      LAST_RUN=$(cat "$LAST_RUN_FILE")
    fi

    if [ "$LAST_RUN" != "$TODAY" ]; then
      log "$COLOR_GREEN" "⏰ Running scheduled update checks as per cron '$CHECK_CRON' at $(date '+%H:%M') on $TODAY"
      perform_update_check
      echo "$TODAY" > "$LAST_RUN_FILE"
      log "$COLOR_GREEN" "✅ Scheduled update checks complete."
      sleep 60  # prevent multiple runs in same minute
    fi
  fi

  CURRENT_TIME=$(date +%H:%M)
  log "$COLOR_BLUE" "📅 Waiting for next scheduled check ($CHECK_CRON). Current time: $CURRENT_TIME"
  sleep 60
done
