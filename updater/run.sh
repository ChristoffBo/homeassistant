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
NOTIFICATION_URL=""
NOTIFICATION_TOKEN=""
NOTIFICATION_TO=""
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
      if [ -z "$NOTIFICATION_URL" ] || [ -z "$NOTIFICATION_TOKEN" ]; then
        log "$COLOR_RED" "❌ Gotify configuration incomplete"
        return
      fi
      curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
        "$NOTIFICATION_URL/message?token=$NOTIFICATION_TOKEN" >> "$LOG_FILE" 2>&1
      ;;
    "mailrise")
      if [ -z "$NOTIFICATION_URL" ] || [ -z "$NOTIFICATION_TO" ]; then
        log "$COLOR_RED" "❌ Mailrise configuration incomplete"
        return
      fi
      curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"to\":\"$NOTIFICATION_TO\", \"subject\":\"$title\", \"body\":\"$message\"}" \
        "$NOTIFICATION_URL" >> "$LOG_FILE" 2>&1
      ;;
    "apprise")
      if [ -z "$NOTIFICATION_URL" ]; then
        log "$COLOR_RED" "❌ Apprise configuration incomplete"
        return
      fi
      apprise -vv -t "$title" -b "$message" "$NOTIFICATION_URL" >> "$LOG_FILE" 2>&1
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
NOTIFICATION_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
if [ "$NOTIFICATION_ENABLED" = "true" ]; then
  NOTIFICATION_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
  NOTIFICATION_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
  NOTIFICATION_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
  NOTIFICATION_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
  NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
  NOTIFY_ON_ERROR=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
  NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")
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

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Cloning repository..."
    if git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      send_notification "Add-on Updater Error" "Failed to clone repository $GITHUB_REPO" 5
      exit 1
    fi
  else
    cd "$REPO_DIR"
    log "$COLOR_PURPLE" "🔄 Pulling latest changes from GitHub..."
    
    # Reset any local changes that might conflict
    git reset --hard HEAD >> "$LOG_FILE" 2>&1
    git clean -fd >> "$LOG_FILE" 2>&1
    
    if ! git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_RED" "❌ Initial git pull failed. Attempting recovery..."
      
      # Check for specific git issues
      if [ -d ".git/rebase-merge" ] || [ -d ".git/rebase-apply" ]; then
        log "$COLOR_YELLOW" "⚠️ Detected unfinished rebase, aborting it..."
        git rebase --abort >> "$LOG_FILE" 2>&1 || true
      fi
      
      # Reset to origin/main
      git fetch origin main >> "$LOG_FILE" 2>&1
      git reset --hard origin/main >> "$LOG_FILE" 2>&1
      
      if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "✅ Git pull successful after recovery."
      else
        log "$COLOR_RED" "❌ Git pull still failed after recovery."
        send_notification "Add-on Updater Error" "Failed to pull repository $GITHUB_REPO after recovery attempts" 5
        exit 1
      fi
    else
      log "$COLOR_GREEN" "✅ Git pull successful."
    fi
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  local latest_version=""
  local retries=3
  
  for ((i=1; i<=retries; i++)); do
    # Try different methods based on image source
    if [[ "$image_name" =~ ^linuxserver/ ]] || [[ "$image_name" =~ ^lscr.io/linuxserver/ ]]; then
      # For linuxserver.io images
      local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
      local api_response=$(curl -s "https://api.linuxserver.io/v1/images/$lsio_name/tags")
      if [ -n "$api_response" ]; then
        latest_version=$(echo "$api_response" | 
                        jq -r '.tags[] | select(.name != "latest") | .name' | 
                        grep -E '^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$' | 
                        sort -Vr | head -n1)
      fi
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
      # For GitHub Container Registry
      local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
      local package=$(echo "$image_name" | cut -d/ -f4)
      local token=$(curl -s "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token')
      if [ -n "$token" ]; then
        latest_version=$(curl -s -H "Authorization: Bearer $token" \
                         "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
                         jq -r '.tags[] | select(. != "latest" and (. | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$")))' | \
                         sort -Vr | head -n1)
      fi
    else
      # For standard Docker Hub images
      local namespace=$(echo "$image_name" | cut -d/ -f1)
      local repo=$(echo "$image_name" | cut -d/ -f2)
      if [ "$namespace" = "$repo" ]; then
        # Official image (library/)
        local api_response=$(curl -s "https://registry.hub.docker.com/v2/repositories/library/$repo/tags/")
        if [ -n "$api_response" ]; then
          latest_version=$(echo "$api_response" | 
                          jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                          sort -Vr | head -n1)
        fi
      else
        # User/org image
        local api_response=$(curl -s "https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/")
        if [ -n "$api_response" ]; then
          latest_version=$(echo "$api_response" | 
                          jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                          sort -Vr | head -n1)
        fi
      fi
    fi

    # If we found a version, break the retry loop
    if [ -n "$latest_version" ] && [ "$latest_version" != "null" ]; then
      break
    fi
    
    if [ $i -lt $retries ]; then
      sleep 5
    fi
  done

  # If we couldn't determine version after retries, use 'latest'
  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Using 'latest' tag for $image after $retries retries"
    echo "latest"
  else
    echo "$latest_version"
  fi
}

get_docker_source_url() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  
  if [[ "$image_name" =~ ^linuxserver/ ]] || [[ "$image_name" =~ ^lscr.io/linuxserver/ ]]; then
    local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
    echo "https://fleet.linuxserver.io/image?name=$lsio_name"
  elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
    local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
    local package=$(echo "$image_name" | cut -d/ -f4)
    echo "https://github.com/$org_repo/pkgs/container/$package"
  else
    local namespace=$(echo "$image_name" | cut -d/ -f1)
    local repo=$(echo "$image_name" | cut -d/ -f2)
    if [ "$namespace" = "$repo" ]; then
      echo "https://hub.docker.com/_/$repo"
    else
      echo "https://hub.docker.com/r/$namespace/$repo"
    fi
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "🧩 Addon: $slug (Current: $current_version)"

  # Get latest version
  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ "$latest_version" != "$current_version" ]; then
    log "$COLOR_GREEN" "⬆️  Update available: $current_version → $latest_version"
    
    if [ "$NOTIFY_ON_UPDATES" = "true" ]; then
      send_notification "Add-on Update Available" "Add-on $slug can be updated from $current_version to $latest_version" 0
    fi
    
    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping actual update"
      return
    fi

    # Update config.json version
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null && \
        mv "$config_file.tmp" "$config_file"
    fi

    # Update or create updater.json
    jq --arg v "$latest_version" --arg dt "$(date '+%Y-%m-%d %H:%M:%S')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date '+%Y-%m-%d %H:%M:%S')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
    mv "$updater_file.tmp" "$updater_file"

    # Update CHANGELOG.md
    local source_url
    source_url=$(get_docker_source_url "$image")
    
    if [ ! -f "$changelog_file" ]; then
      {
        echo "# CHANGELOG for $slug"
        echo "==================="
        echo
        echo "## Initial version: $current_version"
        echo "Docker Image source: [$image]($source_url)"
        echo
      } > "$changelog_file"
    fi

    NEW_ENTRY="\
## $latest_version ($(date '+%Y-%m-%d %H:%M:%S'))

- Update from version $current_version to $latest_version
- Docker Image: [$image]($source_url)

"

    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ Updated $slug to version $latest_version"
  else
    log "$COLOR_GREEN" "✔️ $slug is up to date"
  fi
}

perform_update_check() {
  local start_time=$(date +%s)
  log "$COLOR_PURPLE" "🚀 Starting update check"
  
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local any_updates=0
  local updated_addons=()

  for addon_path in "$REPO_DIR"/*/; do
    if [ -d "$addon_path" ]; then
      if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ]; then
        update_addon_if_needed "$addon_path"
        any_updates=1
      fi
    fi
  done

  if [ "$any_updates" -eq 1 ] && [ "$(git status --porcelain)" ]; then
    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping git commit/push"
      return
    fi
    
    if [ "$SKIP_PUSH" = "true" ]; then
      log "$COLOR_CYAN" "⏸️ Skip push enabled - committing changes locally but not pushing"
      git add .
      git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1
    else
      git add .
      git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1
      if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "✅ Git push successful."
        if [ "$NOTIFY_ON_SUCCESS" = "true" ]; then
          local duration=$(( $(date +%s) - start_time ))
          send_notification "Add-on Updater Success" "Successfully updated add-ons and pushed changes to repository" 0
        fi
      else
        log "$COLOR_RED" "❌ Git push failed."
        if [ "$NOTIFY_ON_ERROR" = "true" ]; then
          send_notification "Add-on Updater Error" "Failed to push changes to repository" 5
        fi
      fi
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found"
    if [ "$NOTIFY_ON_SUCCESS" = "true" ]; then
      local duration=$(( $(date +%s) - start_time ))
      send_notification "Add-on Updater Complete" "No add-on updates were available" 0
    fi
  fi
  
  log "$COLOR_PURPLE" "🏁 Update check completed"
}

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
