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
  echo -e "${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

log_with_timestamp() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

send_notification() {
  local title="$1"
  local message="$2"
  local priority="${3:-0}"
  
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
  log_with_timestamp "$COLOR_RED" "⚠️ Another update process is already running. Exiting."
  exit 1
fi

# Create lock file
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

if [ ! -f "$CONFIG_PATH" ]; then
  log_with_timestamp "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Read configuration
GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH" 2>/dev/null || true)
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH" 2>/dev/null || true)
GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH" 2>/dev/null || true)
CHECK_CRON=$(jq -r '.check_cron // "0 */6 * * *"' "$CONFIG_PATH" 2>/dev/null || true)
STARTUP_CRON=$(jq -r '.startup_cron // empty' "$CONFIG_PATH" 2>/dev/null || true)
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH" 2>/dev/null || true)
MAX_LOG_LINES=$(jq -r '.max_log_lines // 1000' "$CONFIG_PATH" 2>/dev/null || true)
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH" 2>/dev/null || true)
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH" 2>/dev/null || true)

# Read notification configuration
NOTIFICATION_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH" 2>/dev/null || true)
if [ "$NOTIFICATION_ENABLED" = "true" ]; then
  NOTIFICATION_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH" 2>/dev/null || true)
  NOTIFICATION_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH" 2>/dev/null || true)
  NOTIFICATION_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH" 2>/dev/null || true)
  NOTIFICATION_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH" 2>/dev/null || true)
  NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH" 2>/dev/null || true)
  NOTIFY_ON_ERROR=$(jq -r '.notify_on_error // true' "$CONFIG_PATH" 2>/dev/null || true)
  NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH" 2>/dev/null || true)
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
  log "$COLOR_PURPLE" "🔮 Checking GitHub repository for updates..."
  
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_CYAN" "📦 Cloning repository from $GITHUB_REPO..."
    
    if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_TOKEN" ]; then
      log "$COLOR_RED" "❌ GitHub credentials not configured!"
      log "$COLOR_YELLOW" "   Please set github_username and github_token in your addon configuration"
      exit 1
    fi
    
    if ! curl -s -I https://github.com | grep -q "HTTP/.* 200"; then
      log "$COLOR_RED" "❌ Cannot connect to GitHub!"
      log "$COLOR_YELLOW" "   Please check your internet connection"
      exit 1
    fi
    
    if git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"; then
      log "$COLOR_GREEN" "✅ Successfully cloned repository"
    else
      log "$COLOR_RED" "❌ Failed to clone repository"
      log "$COLOR_YELLOW" "╔════════════════════════════════════════════╗"
      log "$COLOR_YELLOW" "║              CLONE ERROR DETAILS            ║"
      log "$COLOR_YELLOW" "╠════════════════════════════════════════════╣"
      tail -n 5 "$LOG_FILE" | while read -r line; do
        log "$COLOR_YELLOW" "║ $line"
      done
      log "$COLOR_YELLOW" "╚════════════════════════════════════════════╝"
      exit 1
    fi
  else
    cd "$REPO_DIR" || {
      log "$COLOR_RED" "❌ Failed to enter repository directory"
      exit 1
    }
    
    log "$COLOR_CYAN" "🔄 Pulling latest changes from GitHub..."
    
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      log "$COLOR_RED" "❌ $REPO_DIR is not a git repository!"
      exit 1
    fi
    
    log "$COLOR_BLUE" "   Current HEAD: $(git rev-parse --short HEAD)"
    log "$COLOR_BLUE" "   Last commit: $(git log -1 --format='%cd %s' --date=format:'%Y-%m-%d %H:%M:%S')"
    
    git reset --hard HEAD >> "$LOG_FILE" 2>&1
    git clean -fd >> "$LOG_FILE" 2>&1
    
    if ! git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_RED" "❌ Initial git pull failed. Attempting recovery..."
      
      if [ -d ".git/rebase-merge" ] || [ -d ".git/rebase-apply" ]; then
        log "$COLOR_YELLOW" "⚠️ Detected unfinished rebase, aborting it..."
        git rebase --abort >> "$LOG_FILE" 2>&1 || true
      fi
      
      git fetch origin main >> "$LOG_FILE" 2>&1
      git reset --hard origin/main >> "$LOG_FILE" 2>&1
      
      if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "✅ Git pull successful after recovery"
        log "$COLOR_BLUE" "   New HEAD: $(git rev-parse --short HEAD)"
      else
        log "$COLOR_RED" "❌ Git pull still failed after recovery attempts"
        tail -n 5 "$LOG_FILE" | sed 's/^/   /' | while read -r line; do log "$COLOR_YELLOW" "$line"; done
        send_notification "Add-on Updater Error" "Failed to pull repository $GITHUB_REPO after recovery attempts" 5
        exit 1
      fi
    else
      log "$COLOR_GREEN" "✅ Successfully pulled latest changes"
      log "$COLOR_BLUE" "   New HEAD: $(git rev-parse --short HEAD)"
      git log --pretty=format:'   %h - %s (%cd)' --date=format:'%Y-%m-%d %H:%M:%S' HEAD@{1}..HEAD 2>/dev/null || log "$COLOR_BLUE" "   (No new commits)"
    fi
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  local retries=3
  local version="latest"
  
  for ((i=1; i<=retries; i++)); do
    if [[ "$image_name" =~ ^linuxserver/ ]] || [[ "$image_name" =~ ^lscr.io/linuxserver/ ]]; then
      local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
      local api_response=$(curl -s "https://api.linuxserver.io/v1/images/$lsio_name/tags")
      if [ -n "$api_response" ]; then
        version=$(echo "$api_response" | 
                 jq -r '.tags[] | select(.name != "latest") | .name' 2>/dev/null | 
                 grep -E '^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?$' | 
                 sort -Vr | head -n1)
      fi
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
      local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
      local package=$(echo "$image_name" | cut -d/ -f4)
      local token=$(curl -s "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token' 2>/dev/null || true)
      if [ -n "$token" ]; then
        version=$(curl -s -H "Authorization: Bearer $token" \
                  "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
                  jq -r '.tags[] | select(. != "latest" and (. | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?$")))' 2>/dev/null | \
                  sort -Vr | head -n1)
      fi
    else
      local namespace=$(echo "$image_name" | cut -d/ -f1)
      local repo=$(echo "$image_name" | cut -d/ -f2)
      if [ "$namespace" = "$repo" ]; then
        local api_response=$(curl -s "https://registry.hub.docker.com/v2/repositories/library/$repo/tags/")
        if [ -n "$api_response" ]; then
          version=$(echo "$api_response" | 
                   jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))) | .name' 2>/dev/null | 
                   sort -Vr | head -n1)
        fi
      else
        local api_response=$(curl -s "https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/")
        if [ -n "$api_response" ]; then
          version=$(echo "$api_response" | 
                   jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))) | .name' 2>/dev/null | 
                   sort -Vr | head -n1)
        fi
      fi
    fi

    if [[ "$version" =~ ^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
      version=${version#v}
      break
    fi
    
    if [ $i -lt $retries ]; then
      sleep 5
    fi
  done

  if [[ ! "$version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    version="latest"
  fi

  echo "$version"
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
    local addon_name=$(basename "$addon_path")
    
    if [[ "$addon_name" == "updater" ]]; then
        log "$COLOR_BLUE" "🔧 Skipping updater addon (self)"
        return
    fi

    log "$COLOR_CYAN" "🔍 Checking add-on: $addon_name"

    local image=""
    local slug="$addon_name"
    local current_version="latest"
    local config_file="$addon_path/config.json"
    local build_file="$addon_path/build.json"

    if [[ -f "$config_file" ]]; then
        log "$COLOR_BLUE" "   Checking config.json"
        image=$(jq -r '.image | select(.!=null)' "$config_file" 2>/dev/null || true)
        slug=$(jq -r '.slug | select(.!=null)' "$config_file" 2>/dev/null || true)
        current_version=$(jq -r '.version | select(.!=null)' "$config_file" 2>/dev/null || echo "latest")
    fi

    if [[ -z "$image" && -f "$build_file" ]]; then
        log "$COLOR_BLUE" "   Checking build.json"
        local arch=$(uname -m)
        [[ "$arch" == "x86_64" ]] && arch="amd64"
        if [ -s "$build_file" ]; then
            image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | if type=="string" then . else empty end' "$build_file" 2>/dev/null || true)
        else
            log "$COLOR_YELLOW" "   ⚠️ build.json is empty"
        fi
    fi

    if [[ -z "$image" ]]; then
        log "$COLOR_YELLOW" "⚠️ No Docker image found in config.json or build.json"
        image="$slug:latest"
    fi

    local latest_version=$(get_latest_docker_tag "$image")
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')

    log "$COLOR_BLUE" "   Current version: $current_version"
    log "$COLOR_BLUE" "   Docker image: $image"
    log "$COLOR_BLUE" "   Available version: $latest_version"

    if [[ "$latest_version" != "$current_version" ]]; then
        log "$COLOR_GREEN" "⬆️ Update available: $current_version → $latest_version"
        
        if [[ "$DRY_RUN" == "true" ]]; then
            log "$COLOR_CYAN" "🛑 Dry run enabled - would update to $latest_version"
            return
        fi

        if [[ -f "$config_file" ]]; then
            if jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null; then
                mv "$config_file.tmp" "$config_file"
                log "$COLOR_GREEN" "✅ Updated version in config.json"
            else
                log "$COLOR_RED" "❌ Failed to update config.json"
            fi
        fi

        if [[ -f "$build_file" ]]; then
            if grep -q 'version' "$build_file"; then
                if jq --arg v "$latest_version" '.version = $v' "$build_file" > "$build_file.tmp" 2>/dev/null; then
                    mv "$build_file.tmp" "$build_file"
                    log "$COLOR_GREEN" "✅ Updated version in build.json"
                else
                    log "$COLOR_RED" "❌ Failed to update build.json"
                fi
            fi
        fi

        update_changelog "$addon_path" "$addon_name" "$current_version" "$latest_version" "$image"
    else
        log "$COLOR_GREEN" "✔️ Already up to date"
    fi
}

update_changelog() {
    local addon_path="$1"
    local slug="$2"
    local current_version="$3"
    local latest_version="$4"
    local image="$5"
    
    local changelog_file="$addon_path/CHANGELOG.md"
    local source_url=$(get_docker_source_url "$image")
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')

    if [[ ! -f "$changelog_file" ]]; then
        printf "# CHANGELOG for %s\n\n## Initial version: %s\nDocker Image: [%s](%s)\n\n" \
            "$slug" "$current_version" "$image" "$source_url" > "$changelog_file"
        log "$COLOR_BLUE" "   Created new CHANGELOG.md"
    fi

    local new_entry="## $latest_version ($update_time)\n- Update from $current_version to $latest_version\n- Docker Image: [$image]($source_url)\n\n"
    printf "%b$(cat "$changelog_file")" "$new_entry" > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"
    
    log "$COLOR_GREEN" "✅ Updated CHANGELOG.md"
}

perform_update_check() {
  local start_time=$(date +%s)
  log_with_timestamp "$COLOR_PURPLE" "🚀 Starting update check"
  
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local any_updates=0

  for addon_path in "$REPO_DIR"/*/; do
    if [ -d "$addon_path" ]; then
      update_addon_if_needed "$addon_path"
      any_updates=1
    fi
  done

  if [ "$any_updates" -eq 1 ] && [ "$(git status --porcelain)" ]; then
    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping git commit/push"
    else
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
            send_notification "Add-on Updater Success" "Successfully updated add-ons and pushed changes to repository" 0
          fi
        else
          log "$COLOR_RED" "❌ Git push failed."
          if [ "$NOTIFY_ON_ERROR" = "true" ]; then
            send_notification "Add-on Updater Error" "Failed to push changes to repository" 5
          fi
        fi
      fi
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found"
  fi
  
  local end_time=$(date +%s)
  local duration=$((end_time - start_time))
  log_with_timestamp "$COLOR_PURPLE" "🏁 Update check completed in ${duration} seconds"
}

should_run_from_cron() {
  local cron_schedule="$1"
  if [ -z "$cron_schedule" ]; then
    return 1
  fi

  local current_minute=$(date '+%M')
  local current_hour=$(date '+%H')
  local current_day=$(date '+%d')
  local current_month=$(date '+%m')
  local current_weekday=$(date '+%w')

  local cron_minute=$(echo "$cron_schedule" | awk '{print $1}')
  local cron_hour=$(echo "$cron_schedule" | awk '{print $2}')
  local cron_day=$(echo "$cron_schedule" | awk '{print $3}')
  local cron_month=$(echo "$cron_schedule" | awk '{print $4}')
  local cron_weekday=$(echo "$cron_schedule" | awk '{print $5}')

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
log_with_timestamp "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
log "$COLOR_GREEN" "⚙️ Configuration:"
log "$COLOR_GREEN" "   - GitHub Repo: $GITHUB_REPO"
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
  if [ -n "$STARTUP_CRON" ] && should_run_from_cron "$STARTUP_CRON"; then
    log "$COLOR_BLUE" "⏰ Startup cron triggered ($STARTUP_CRON)"
    perform_update_check
  fi

  if should_run_from_cron "$CHECK_CRON"; then
    log "$COLOR_BLUE" "⏰ Check cron triggered ($CHECK_CRON)"
    perform_update_check
  fi

  sleep 60
done