#!/usr/bin/with-contenv bashio
set -eo pipefail

# ==============================================================================
# GLOBAL CONFIGURATION
# ==============================================================================
CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
MAX_LOG_LINES=1000

# ==============================================================================
# COLOR DEFINITIONS
# ==============================================================================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# ==============================================================================
# INITIALIZATION
# ==============================================================================
mkdir -p "$(dirname "$LOG_FILE")"
: > "$LOG_FILE"

# ==============================================================================
# FUNCTIONS
# ==============================================================================

# Logging function with color support
log() {
  local color="$1"
  shift
  local message="$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}"
  echo -e "$message" | tee -a "$LOG_FILE"
}

# Sanitize version strings
sanitize_version() {
  echo "$1" | sed -e 's/\x1b\[[0-9;]*m//g' -e 's/[^a-zA-Z0-9._-]//g'
}

# Validate version tag format
validate_version_tag() {
  local version=$(sanitize_version "$1")
  [[ "$version" =~ ^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$ ]] || \
  [[ "$version" == "latest" ]]
}

# Verify config version with retries
verify_config_version() {
  local config_file="$1"
  local max_attempts=3
  
  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    [[ -f "$config_file" ]] || return 1
    
    local current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null || echo "")
    current_version=$(sanitize_version "$current_version")
    
    if validate_version_tag "$current_version"; then
      return 0
    fi
    
    log "$COLOR_YELLOW" "⚠️ Invalid version in $config_file, attempt $attempt/$max_attempts"
    [[ $attempt -lt $max_attempts ]] && sleep 1
  done
  
  log "$COLOR_RED" "❌ Failed to validate version in $config_file after $max_attempts attempts"
  return 1
}

# Safely write version to file with atomic operations
write_safe_version() {
  local file="$1"
  local version="$2"
  local max_attempts=3
  local attempt=0
  
  version=$(sanitize_version "$version")
  [[ -f "$file" ]] || return 1
  
  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    # Create backup and new content
    cp -f "$file" "${file}.bak"
    local new_content=$(jq --arg v "$version" '.version = $v' "$file" 2>/dev/null)
    
    if [[ -n "$new_content" ]] && jq -e . >/dev/null 2>&1 <<<"$new_content"; then
      # Atomic write operation
      echo "$new_content" > "${file}.tmp" && mv "${file}.tmp" "$file"
      
      if verify_config_version "$file"; then
        rm -f "${file}.bak"
        return 0
      else
        mv -f "${file}.bak" "$file"
      fi
    fi
    
    log "$COLOR_YELLOW" "⚠️ Version write attempt $attempt/$max_attempts failed for $file"
    [[ $attempt -lt $max_attempts ]] && sleep 1
  done
  
  log "$COLOR_RED" "❌ Failed to write version to $file after $max_attempts attempts"
  return 1
}

# Send notifications
send_notification() {
  local title="$1"
  local message="$2"
  local priority="${3:-0}"
  
  [[ "${NOTIFICATION_ENABLED}" != "true" ]] && return

  case "${NOTIFICATION_SERVICE}" in
    "gotify")
      [[ -z "${NOTIFICATION_URL}" || -z "${NOTIFICATION_TOKEN}" ]] && {
        log "$COLOR_RED" "❌ Gotify configuration incomplete"
        return
      }
      curl -sS -X POST \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
        "${NOTIFICATION_URL}/message?token=${NOTIFICATION_TOKEN}" >> "$LOG_FILE" 2>&1 || \
        log "$COLOR_YELLOW" "⚠️ Failed to send Gotify notification"
      ;;
    "mailrise")
      [[ -z "${NOTIFICATION_URL}" || -z "${NOTIFICATION_TO}" ]] && {
        log "$COLOR_RED" "❌ Mailrise configuration incomplete"
        return
      }
      curl -sS -X POST \
        -H "Content-Type: application/json" \
        -d "{\"to\":\"${NOTIFICATION_TO}\", \"subject\":\"$title\", \"body\":\"$message\"}" \
        "${NOTIFICATION_URL}" >> "$LOG_FILE" 2>&1 || \
        log "$COLOR_YELLOW" "⚠️ Failed to send Mailrise notification"
      ;;
    "apprise")
      [[ -z "${NOTIFICATION_URL}" ]] && {
        log "$COLOR_RED" "❌ Apprise configuration incomplete"
        return
      }
      apprise -vv -t "$title" -b "$message" "${NOTIFICATION_URL}" >> "$LOG_FILE" 2>&1 || \
        log "$COLOR_YELLOW" "⚠️ Failed to send Apprise notification"
      ;;
    *)
      log "$COLOR_YELLOW" "⚠️ Unknown notification service: ${NOTIFICATION_SERVICE}"
      ;;
  esac
}

# Clone or update repository
clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking GitHub repository for updates..."
  
  if [[ ! -d "$REPO_DIR" ]]; then
    log "$COLOR_CYAN" "📦 Cloning repository from ${GITHUB_REPO}..."
    
    if [[ -z "$GITHUB_USERNAME" || -z "$GITHUB_TOKEN" ]]; then
      log "$COLOR_RED" "❌ GitHub credentials not configured!"
      log "$COLOR_YELLOW" "   Please set github_username and github_token in your addon configuration"
      exit 1
    fi
    
    if ! curl -sS --connect-timeout 10 https://github.com >/dev/null 2>&1; then
      log "$COLOR_RED" "❌ Cannot connect to GitHub!"
      log "$COLOR_YELLOW" "   Please check your internet connection"
      exit 1
    fi
    
    if git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
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
      
      if [[ -d ".git/rebase-merge" || -d ".git/rebase-apply" ]]; then
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
        log "$COLOR_YELLOW" "   Error details:"
        tail -n 5 "$LOG_FILE" | sed 's/^/   /' | while read -r line; do 
          log "$COLOR_YELLOW" "$line"
        done
        send_notification "Add-on Updater Error" "Failed to pull repository $GITHUB_REPO after recovery attempts" 5
        exit 1
      fi
    else
      log "$COLOR_GREEN" "✅ Successfully pulled latest changes"
      log "$COLOR_BLUE" "   New HEAD: $(git rev-parse --short HEAD)"
      git log --pretty=format:'   %h - %s (%cd)' --date=format:'%Y-%m-%d %H:%M:%S' HEAD@{1}..HEAD 2>/dev/null || 
        log "$COLOR_BLUE" "   (No new commits)"
    fi
  fi
}

# Get latest Docker tag with retries
get_latest_docker_tag() {
  local image="$1"
  local image_name=$(echo "$image" | cut -d: -f1)
  local latest_version=""
  
  for ((i=1; i<=3; i++)); do
    if [[ "$image_name" =~ ^linuxserver/ ]] || [[ "$image_name" =~ ^lscr.io/linuxserver/ ]]; then
      local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
      local api_response=$(curl -sS "https://api.linuxserver.io/v1/images/$lsio_name/tags")
      if [[ -n "$api_response" ]]; then
        latest_version=$(echo "$api_response" | 
                        jq -r '.tags[] | select(.name != "latest") | .name' | 
                        grep -E '^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$' | 
                        sort -Vr | head -n1)
      fi
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
      local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
      local package=$(echo "$image_name" | cut -d/ -f4)
      local token=$(curl -sS "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token // empty')
      if [[ -n "$token" ]]; then
        latest_version=$(curl -sS -H "Authorization: Bearer $token" \
                         "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
                         jq -r '.tags[] | select(. != "latest" and (. | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$")))' | \
                         sort -Vr | head -n1)
      fi
    else
      local namespace=$(echo "$image_name" | cut -d/ -f1)
      local repo=$(echo "$image_name" | cut -d/ -f2)
      if [[ "$namespace" == "$repo" ]]; then
        local api_response=$(curl -sS "https://registry.hub.docker.com/v2/repositories/library/$repo/tags/")
        if [[ -n "$api_response" ]]; then
          latest_version=$(echo "$api_response" | 
                          jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                          sort -Vr | head -n1)
        fi
      else
        local api_response=$(curl -sS "https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/")
        if [[ -n "$api_response" ]]; then
          latest_version=$(echo "$api_response" | 
                          jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?(-[a-zA-Z0-9]+)?$"))) | .name' | 
                          sort -Vr | head -n1)
        fi
      fi
    fi

    latest_version=$(sanitize_version "$latest_version")
    validate_version_tag "$latest_version" && break
    [[ $i -lt 3 ]] && sleep 5
  done

  [[ -z "$latest_version" ]] && latest_version="latest"
  echo "$latest_version"
}

# Get Docker source URL
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
    if [[ "$namespace" == "$repo" ]]; then
      echo "https://hub.docker.com/_/$repo"
    else
      echo "https://hub.docker.com/r/$namespace/$repo"
    fi
  fi
}

# Update add-on if needed
update_addon_if_needed() {
  local addon_path="$1"
  local addon_name=$(basename "$addon_path")
  
  [[ "$addon_name" == "updater" ]] && {
    log "$COLOR_BLUE" "🔧 Skipping updater addon (self)"
    return
  }

  log "$COLOR_CYAN" "🔍 Checking add-on: $addon_name"

  local image="" slug="$addon_name" current_version="latest" upstream_version="latest" last_update="Never"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local updater_file="$addon_path/updater.json"

  # Load current config
  if [[ -f "$config_file" ]]; then
    if ! verify_config_version "$config_file"; then
      log "$COLOR_RED" "❌ Existing config.json has invalid version, resetting to 'latest'"
      current_version="latest"
    else
      current_version=$(sanitize_version "$(jq -r '.version // "latest"' "$config_file" 2>/dev/null || echo "latest")")
      image=$(jq -r '.image // empty' "$config_file" 2>/dev/null || echo "")
      slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null || echo "$addon_name")
    fi
  fi

  # Handle build.json
  if [[ -z "$image" && -f "$build_file" ]]; then
    log "$COLOR_BLUE" "   Checking build.json"
    local arch=$(uname -m)
    [[ "$arch" == "x86_64" ]] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from // empty | if type=="string" then . else empty end' "$build_file" 2>/dev/null || echo "")
  fi

  [[ -z "$image" ]] && {
    log "$COLOR_YELLOW" "⚠️ No Docker image found in config.json or build.json"
    image="$slug:latest"
  }

  local update_time=$(date '+%Y-%m-%d %H:%M:%S')
  
  # Handle updater.json
  if [[ -f "$updater_file" ]]; then
    upstream_version=$(sanitize_version "$(jq -r '.upstream_version // "latest"' "$updater_file" 2>/dev/null || echo "latest")")
    last_update=$(jq -r '.last_update // empty' "$updater_file" 2>/dev/null || echo "Never")
    
    local updater_content=$(jq --arg image "$image" --arg slug "$slug" \
       '.image = $image | .slug = $slug' "$updater_file" 2>/dev/null || \
       jq -n --arg image "$image" --arg slug "$slug" \
       '{image: $image, slug: $slug, upstream_version: "latest", last_update: "Never"}')
    echo "$updater_content" > "$updater_file"
  else
    jq -n --arg slug "$slug" --arg image "$image" \
        --arg upstream "latest" --arg updated "$update_time" \
        '{
            slug: $slug,
            image: $image,
            upstream_version: $upstream,
            last_update: $updated
        }' > "$updater_file"
  fi

  log "$COLOR_BLUE" "   Current version: $current_version"
  log "$COLOR_BLUE" "   Docker image: $image"
  log "$COLOR_BLUE" "   Last update: ${last_update:-Never}"

  # Get latest version
  local latest_version=""
  for ((i=1; i<=3; i++)); do
    latest_version=$(get_latest_docker_tag "$image")
    latest_version=$(sanitize_version "$latest_version")
    validate_version_tag "$latest_version" && break
    [[ $i -lt 3 ]] && sleep 5
  done

  [[ -z "$latest_version" ]] && latest_version="latest"

  if [[ "$latest_version" != "$current_version" ]]; then
    log "$COLOR_GREEN" "⬆️ Update available: $current_version → $latest_version"
    
    [[ "$DRY_RUN" == "true" ]] && {
      log "$COLOR_CYAN" "🛑 Dry run enabled - would update to $latest_version"
      return
    }

    # Update config.json
    if [[ -f "$config_file" ]]; then
      if write_safe_version "$config_file" "$latest_version"; then
        log "$COLOR_GREEN" "✅ Verified version update in config.json"
      else
        log "$COLOR_RED" "❌ Failed to safely update config.json"
      fi
    fi

    # Update updater.json
    if [[ -f "$updater_file" ]]; then
      local new_updater_content=$(jq --arg v "$latest_version" --arg dt "$update_time" \
          '.upstream_version = $v | .last_update = $dt' "$updater_file" 2>/dev/null || \
          jq -n --arg v "$latest_version" --arg dt "$update_time" \
          '{upstream_version: $v, last_update: $dt}')
      echo "$new_updater_content" > "$updater_file"
    fi

    update_changelog "$addon_path" "$slug" "$current_version" "$latest_version" "$image"
  else
    log "$COLOR_GREEN" "✔️ Already up to date"
  fi
}

# Update changelog
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
      "$slug" "$current_version" "$image" "$source_url" > "$changelog_file" || {
      log "$COLOR_RED" "❌ Failed to create CHANGELOG.md"
      return
    }
    log "$COLOR_BLUE" "   Created new CHANGELOG.md"
  fi

  local new_entry="## $latest_version ($update_time)\n- Update from $current_version to $latest_version\n- Docker Image: [$image]($source_url)\n\n"
  if ! printf "%b$(cat "$changelog_file")" "$new_entry" > "${changelog_file}.tmp" || \
     ! mv "${changelog_file}.tmp" "$changelog_file"; then
    log "$COLOR_RED" "❌ Failed to update CHANGELOG.md"
    return
  fi
  
  log "$COLOR_GREEN" "✅ Updated CHANGELOG.md"
}

# Perform update check
perform_update_check() {
  local start_time=$(date +%s)
  log "$COLOR_PURPLE" "🚀 Starting update check"
  
  clone_or_update_repo

  cd "$REPO_DIR" || exit 1
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local any_updates=0

  for addon_path in "$REPO_DIR"/*/; do
    [[ -d "$addon_path" ]] && {
      update_addon_if_needed "$addon_path"
      any_updates=1
    }
  done

  if [[ "$any_updates" -eq 1 && -n "$(git status --porcelain)" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping git commit/push"
      return
    fi
    
    if [[ "$SKIP_PUSH" == "true" ]]; then
      log "$COLOR_CYAN" "⏸️ Skip push enabled - committing changes locally but not pushing"
      git add .
      git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1
    else
      git add .
      if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
        if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
          log "$COLOR_GREEN" "✅ Git push successful."
          [[ "$NOTIFY_ON_SUCCESS" == "true" ]] && {
            local duration=$(( $(date +%s) - start_time ))
            send_notification "Add-on Updater Success" "Successfully updated add-ons and pushed changes to repository" 0
          }
        else
          log "$COLOR_RED" "❌ Git push failed."
          [[ "$NOTIFY_ON_ERROR" == "true" ]] && {
            send_notification "Add-on Updater Error" "Failed to push changes to repository" 5
          }
        fi
      else
        log "$COLOR_RED" "❌ Git commit failed."
      fi
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found"
    [[ "$NOTIFY_ON_SUCCESS" == "true" ]] && {
      local duration=$(( $(date +%s) - start_time ))
      send_notification "Add-on Updater Complete" "No add-on updates were available" 0
    }
  fi
  
  log "$COLOR_PURPLE" "🏁 Update check completed in $(( $(date +%s) - start_time )) seconds"
}

# Check if should run from cron
should_run_from_cron() {
  local cron_schedule="$1"
  [[ -z "$cron_schedule" ]] && return 1

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

  [[ "$cron_minute" != "*" && "$cron_minute" != "$current_minute" ]] && return 1
  [[ "$cron_hour" != "*" && "$cron_hour" != "$current_hour" ]] && return 1
  [[ "$cron_day" != "*" && "$cron_day" != "$current_day" ]] && return 1
  [[ "$cron_month" != "*" && "$cron_month" != "$current_month" ]] && return 1
  [[ "$cron_weekday" != "*" && "$cron_weekday" != "$current_weekday" ]] && return 1

  return 0
}

# ==============================================================================
# MAIN SCRIPT
# ==============================================================================

# Check for lock file
if [[ -f "$LOCK_FILE" ]]; then
  log "$COLOR_RED" "⚠️ Another update process is already running. Exiting."
  exit 1
fi

touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE" 2>/dev/null || true' EXIT

# Load configuration
if [[ ! -f "$CONFIG_PATH" ]]; then
  log "$COLOR_RED" "❌ Config file $CONFIG_PATH not found!"
  exit 1
fi

# Load main config
GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron // "0 */6 * * *"' "$CONFIG_PATH")
STARTUP_CRON=$(jq -r '.startup_cron // empty' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
MAX_LOG_LINES=$(jq -r '.max_log_lines // 1000' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")

# Load notification config
NOTIFICATION_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
if [[ "$NOTIFICATION_ENABLED" == "true" ]]; then
  NOTIFICATION_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
  NOTIFICATION_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
  NOTIFICATION_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
  NOTIFICATION_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
  NOTIFY_ON_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
  NOTIFY_ON_ERROR=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
  NOTIFY_ON_UPDATES=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")
fi

export TZ="$TIMEZONE"

# Set authenticated repo URL
GIT_AUTH_REPO="$GITHUB_REPO"
if [[ -n "$GITHUB_USERNAME" && -n "$GITHUB_TOKEN" ]]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#(https?://)#\1$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Rotate logs
if [[ -f "$LOG_FILE" ]] && [[ $(wc -l < "$LOG_FILE") -gt $MAX_LOG_LINES ]]; then
  log "$COLOR_YELLOW" "📜 Log file too large, rotating..."
  tail -n "$MAX_LOG_LINES" "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

# Initial startup message
log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
log "$COLOR_GREEN" "⚙️ Configuration:"
log "$COLOR_GREEN" "   - GitHub Repo: $GITHUB_REPO"
log "$COLOR_GREEN" "   - Dry run: $DRY_RUN"
log "$COLOR_GREEN" "   - Skip push: $SKIP_PUSH"
log "$COLOR_GREEN" "   - Check cron: $CHECK_CRON"
log "$COLOR_GREEN" "   - Startup cron: ${STARTUP_CRON:-none}"
if [[ "$NOTIFICATION_ENABLED" == "true" ]]; then
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
  if [[ -n "$STARTUP_CRON" ]] && should_run_from_cron "$STARTUP_CRON"; then
    log "$COLOR_BLUE" "⏰ Startup cron triggered ($STARTUP_CRON)"
    perform_update_check
  fi

  if should_run_from_cron "$CHECK_CRON"; then
    log "$COLOR_BLUE" "⏰ Check cron triggered ($CHECK_CRON)"
    perform_update_check
  fi

  sleep 60
done