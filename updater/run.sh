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

# Notification variables (removed for brevity - keep from previous version)

# Clear log file on startup
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# send_notification() function remains the same

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking GitHub repository for updates..."
  
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_CYAN" "📦 Cloning repository from $GITHUB_REPO..."
    if git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Successfully cloned repository"
      log "$COLOR_BLUE" "   Repository location: $REPO_DIR"
    else
      log "$COLOR_RED" "❌ Failed to clone repository from $GITHUB_REPO"
      log "$COLOR_YELLOW" "   Error details:"
      tail -n 5 "$LOG_FILE" | sed 's/^/   /' | while read -r line; do log "$COLOR_YELLOW" "$line"; done
      send_notification "Add-on Updater Error" "Failed to clone repository $GITHUB_REPO" 5
      exit 1
    fi
  else
    cd "$REPO_DIR"
    log "$COLOR_CYAN" "🔄 Pulling latest changes from GitHub..."
    
    # Show current commit info before pull
    log "$COLOR_BLUE" "   Current HEAD: $(git rev-parse --short HEAD)"
    log "$COLOR_BLUE" "   Last commit: $(git log -1 --format='%cd %s' --date=format:'%Y-%m-%d %H:%M:%S')"
    
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
        log "$COLOR_GREEN" "✅ Git pull successful after recovery"
        log "$COLOR_BLUE" "   New HEAD: $(git rev-parse --short HEAD)"
      else
        log "$COLOR_RED" "❌ Git pull still failed after recovery attempts"
        log "$COLOR_YELLOW" "   Error details:"
        tail -n 5 "$LOG_FILE" | sed 's/^/   /' | while read -r line; do log "$COLOR_YELLOW" "$line"; done
        send_notification "Add-on Updater Error" "Failed to pull repository $GITHUB_REPO after recovery attempts" 5
        exit 1
      fi
    else
      log "$COLOR_GREEN" "✅ Successfully pulled latest changes"
      log "$COLOR_BLUE" "   New HEAD: $(git rev-parse --short HEAD)"
      log "$COLOR_BLUE" "   Changes since last update:"
      git log --pretty=format:'   %h - %s (%cd)' --date=format:'%Y-%m-%d %H:%M:%S' HEAD@{1}..HEAD 2>/dev/null || log "$COLOR_BLUE" "   (No new commits)"
    fi
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local addon_name=$(basename "$addon_path")
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  log "$COLOR_CYAN" "🔍 Checking add-on: $addon_name"
  
  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Skipping $addon_name - missing config.json and build.json"
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
    log "$COLOR_YELLOW" "⚠️ Skipping $addon_name - no Docker image defined"
    return
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$addon_name
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  local last_update="Never"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // "Never"' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "   Current version: $current_version"
  log "$COLOR_BLUE" "   Last updated: $last_update"
  log "$COLOR_BLUE" "   Docker image: $image"

  # Get latest version
  log "$COLOR_PURPLE" "   Checking for updates..."
  local latest_version
  latest_version=$(get_latest_docker_tag "$image")
  log "$COLOR_BLUE" "   Latest available: $latest_version"

  if [ "$latest_version" != "$current_version" ]; then
    log "$COLOR_GREEN" "⬆️  Update available: $current_version → $latest_version"
    
    if [ "$NOTIFY_ON_UPDATES" = "true" ]; then
      send_notification "Add-on Update Available" "Add-on $slug can be updated from $current_version to $latest_version" 0
    fi
    
    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - update would change version to $latest_version"
      return
    fi

    # Update config.json version
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null && \
        mv "$config_file.tmp" "$config_file"
    fi

    # Update or create updater.json
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')
    jq --arg v "$latest_version" --arg dt "$update_time" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$update_time" \
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
      log "$COLOR_BLUE" "   Created new CHANGELOG.md"
    fi

    NEW_ENTRY="## $latest_version ($update_time)\n- Update from $current_version to $latest_version\n- Docker Image: [$image]($source_url)\n\n"
    {
      head -n 2 "$changelog_file"
      echo -e "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ Successfully updated $slug to version $latest_version"
    log "$COLOR_BLUE" "   Update time: $update_time"
  else
    log "$COLOR_GREEN" "✔️ $slug is up to date"
  fi
}

# perform_update_check() and other functions remain the same

# Main execution
log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
log "$COLOR_GREEN" "⚙️ Configuration:"
log "$COLOR_GREEN" "   - Dry run: $DRY_RUN"
log "$COLOR_GREEN" "   - Skip push: $SKIP_PUSH"
log "$COLOR_GREEN" "   - Check cron: $CHECK_CRON"
log "$COLOR_GREEN" "   - Startup cron: ${STARTUP_CRON:-none}"

# First run on startup
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check

# Main loop
log "$COLOR_GREEN" "⏳ Waiting for cron triggers..."
while true; do
  sleep 60
done
