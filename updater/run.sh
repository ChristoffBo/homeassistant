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

# Clear log file on startup
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
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
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
MAX_LOG_LINES=$(jq -r '.max_log_lines // 1000' "$CONFIG_PATH")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")

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
        log "$COLOR_RED" "❌ Git pull still failed after recovery. Last 20 log lines:"
        tail -n 20 "$LOG_FILE" | sed 's/^/    /'
        exit 1
      fi
    else
      log "$COLOR_GREEN" "✅ Git pull successful."
    fi
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local log_prefix="$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${COLOR_CYAN}🔍 Checking latest version for $image${COLOR_RESET}"
  echo "$log_prefix" >> "$LOG_FILE"
  
  # Remove :latest or other tags if present
  local image_name=$(echo "$image" | cut -d: -f1)
  local latest_version=""
  
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

  # If we couldn't determine version, log the error
  if [ -z "$latest_version" ]; then
    echo "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${COLOR_RED}❌ Failed to get version for $image${COLOR_RESET}" >> "$LOG_FILE"
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

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  # Get latest version without logging (we already logged the check)
  local latest_version
  latest_version=$(get_latest_docker_tag "$image" 2>/dev/null)

  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ] || [ "$latest_version" == "latest" ]; then
    log "$COLOR_YELLOW" "⚠️ Could not determine latest version for $image, skipping update."
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

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
    log "$COLOR_YELLOW" "🆕 Created new CHANGELOG.md for $slug with current version $current_version and source URL"
  fi

  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Update available for $slug: $current_version → $latest_version"
    
    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping actual update"
      log "$COLOR_BLUE" "----------------------------"
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
    NEW_ENTRY="\
## v$latest_version ($(date '+%Y-%m-%d %H:%M:%S'))

- Update from version $current_version to $latest_version
- Docker Image: [$image]($source_url)

"

    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ Updated $slug to version $latest_version"
    log "$COLOR_GREEN" "📝 Updated CHANGELOG.md for $slug"

  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  log "$COLOR_PURPLE" "🚀 Starting update check at $(date)"
  
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
      else
        log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json or build.json found"
      fi
    fi
  done

  if [ "$any_updates" -eq 1 ] && [ "$(git status --porcelain)" ]; then
    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping git commit/push"
      git diff
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
      else
        log "$COLOR_RED" "❌ Git push failed. See log for details."
      fi
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
  
  log "$COLOR_PURPLE" "🏁 Update check completed at $(date)"
}

# Main execution
log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "⚙️ Configuration:"
log "$COLOR_GREEN" "   - Dry run: $DRY_RUN"
log "$COLOR_GREEN" "   - Skip push: $SKIP_PUSH"
log "$COLOR_GREEN" "   - Max log lines: $MAX_LOG_LINES"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check
log "$COLOR_GREEN" "⏳ Waiting for cron to trigger..."

# Main loop
while true; do
  current_hour=$(date '+%H:%M')
  if [[ "$CHECK_CRON" == *"$current_hour"* ]] || [[ "$current_hour" == "00:00" ]]; then
    perform_update_check
  fi
  sleep 60
done