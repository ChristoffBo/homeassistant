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

# Safely get JSON value with default
get_json_value() {
  local file="$1"
  local key="$2"
  local default="$3"
  
  if [[ ! -f "$file" ]]; then
    echo "$default"
    return
  fi

  local value=$(jq -r --arg d "$default" ".${key} // \$d" "$file" 2>/dev/null || echo "$default")
  echo "$value"
}

# Sanitize version strings
sanitize_version() {
  echo "$1" | sed -e 's/\x1b\[[0-9;]*m//g' -e 's/[^a-zA-Z0-9._-]//g'
}

# Validate version tag format
validate_version_tag() {
  local version=$(sanitize_version "$1")
  [[ -z "$version" ]] && return 1
  [[ "$version" == "latest" ]] && return 0
  [[ "$version" =~ ^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9]+)?$ ]]
}

# Verify config version
verify_config_version() {
  local config_file="$1"
  
  [[ -f "$config_file" ]] || {
    log "$COLOR_RED" "❌ Config file $config_file does not exist"
    return 1
  }

  local current_version=$(get_json_value "$config_file" "version" "latest")
  current_version=$(sanitize_version "$current_version")

  if validate_version_tag "$current_version"; then
    return 0
  fi

  log "$COLOR_RED" "❌ Invalid version format in $config_file: '$current_version'"
  return 1
}

# Safely write version to file
write_safe_version() {
  local file="$1"
  local version="$2"
  
  version=$(sanitize_version "$version")
  [[ -f "$file" ]] || {
    log "$COLOR_RED" "❌ Config file $file does not exist"
    return 1
  }

  # Create backup
  cp -f "$file" "${file}.bak"

  # Try to update version
  if jq --arg v "$version" '.version = $v' "$file" > "${file}.tmp" 2>/dev/null; then
    if jq -e . "${file}.tmp" >/dev/null 2>&1; then
      mv "${file}.tmp" "$file"
      log "$COLOR_GREEN" "✅ Successfully updated version to $version in $file"
      rm -f "${file}.bak"
      return 0
    fi
  fi

  # Restore backup if update failed
  log "$COLOR_RED" "❌ Failed to update version in $file"
  mv -f "${file}.bak" "$file"
  return 1
}

# Update add-on if needed
update_addon_if_needed() {
  local addon_path="${1%/}"  # Remove trailing slash
  local addon_name=$(basename "$addon_path")
  
  [[ "$addon_name" == "updater" ]] && {
    log "$COLOR_BLUE" "🔧 Skipping updater addon (self)"
    return
  }

  log "$COLOR_CYAN" "🔍 Checking add-on: $addon_name"

  local config_file="$addon_path/config.json"
  local updater_file="$addon_path/updater.json"
  
  # Initialize updater file if it doesn't exist
  if [[ ! -f "$updater_file" ]]; then
    jq -n --arg updated "$(date '+%Y-%m-%d %H:%M:%S')" \
      '{
        last_update: $updated,
        upstream_version: "latest"
      }' > "$updater_file"
  fi

  # Get current version
  local current_version=$(get_json_value "$config_file" "version" "latest")
  current_version=$(sanitize_version "$current_version")

  # Validate current version
  if ! validate_version_tag "$current_version"; then
    log "$COLOR_RED" "❌ Invalid current version '$current_version', resetting to 'latest'"
    if ! write_safe_version "$config_file" "latest"; then
      log "$COLOR_RED" "❌ Failed to reset version to 'latest'"
      return 1
    fi
    current_version="latest"
  fi

  # Get last update time
  local last_update=$(get_json_value "$updater_file" "last_update" "Never")

  log "$COLOR_BLUE" "   Current version: $current_version"
  log "$COLOR_BLUE" "   Last update: $last_update"

  # Check for updates (simplified - replace with your actual version check)
  local latest_version="latest"
  
  if [[ "$latest_version" != "$current_version" ]]; then
    log "$COLOR_GREEN" "⬆️ Update available: $current_version → $latest_version"
    
    if [[ "$DRY_RUN" != "true" ]]; then
      if write_safe_version "$config_file" "$latest_version"; then
        # Update updater file
        jq --arg v "$latest_version" --arg updated "$(date '+%Y-%m-%d %H:%M:%S')" \
          '.upstream_version = $v | .last_update = $updated' \
          "$updater_file" > "${updater_file}.tmp" && \
          mv "${updater_file}.tmp" "$updater_file"
      fi
    else
      log "$COLOR_CYAN" "🛑 Dry run enabled - would update to $latest_version"
    fi
  else
    log "$COLOR_GREEN" "✔️ Already up to date"
  fi
}

# Clone or update repository
clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking GitHub repository..."
  
  if [[ ! -d "$REPO_DIR" ]]; then
    log "$COLOR_CYAN" "📦 Cloning repository from ${GITHUB_REPO}..."
    git clone "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1 || {
      log "$COLOR_RED" "❌ Failed to clone repository"
      exit 1
    }
  else
    cd "$REPO_DIR" || {
      log "$COLOR_RED" "❌ Failed to enter repository directory"
      exit 1
    }
    
    log "$COLOR_CYAN" "🔄 Pulling latest changes..."
    git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1 || {
      log "$COLOR_RED" "❌ Failed to pull updates"
      exit 1
    }
  fi
}

# Perform update check
perform_update_check() {
  local start_time=$(date +%s)
  log "$COLOR_PURPLE" "🚀 Starting update check"
  
  clone_or_update_repo

  cd "$REPO_DIR" || {
    log "$COLOR_RED" "❌ Failed to enter repository directory"
    exit 1
  }

  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  for addon_path in "$REPO_DIR"/*/; do
    [[ -d "$addon_path" ]] && update_addon_if_needed "$addon_path"
  done

  if [[ -n "$(git status --porcelain)" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
      log "$COLOR_CYAN" "🛑 Dry run enabled - skipping git commit/push"
    elif [[ "$SKIP_PUSH" == "true" ]]; then
      log "$COLOR_CYAN" "⏸️ Skip push enabled - committing changes locally"
      git add .
      git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || \
        log "$COLOR_RED" "❌ Git commit failed"
    else
      git add .
      if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
        if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
          log "$COLOR_GREEN" "✅ Changes pushed successfully"
        else
          log "$COLOR_RED" "❌ Git push failed"
        fi
      else
        log "$COLOR_RED" "❌ Git commit failed"
      fi
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found"
  fi
  
  log "$COLOR_PURPLE" "🏁 Update check completed in $(( $(date +%s) - start_time )) seconds"
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
GITHUB_REPO=$(get_json_value "$CONFIG_PATH" "github_repo" "")
GITHUB_USERNAME=$(get_json_value "$CONFIG_PATH" "github_username" "")
GITHUB_TOKEN=$(get_json_value "$CONFIG_PATH" "github_token" "")
DRY_RUN=$(get_json_value "$CONFIG_PATH" "dry_run" "false")
SKIP_PUSH=$(get_json_value "$CONFIG_PATH" "skip_push" "false")

# Validate GitHub config
if [[ -z "$GITHUB_REPO" ]]; then
  log "$COLOR_RED" "❌ GitHub repository not configured!"
  exit 1
fi

# Set authenticated repo URL
if [[ -n "$GITHUB_USERNAME" && -n "$GITHUB_TOKEN" ]]; then
  GIT_AUTH_REPO="https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@$(echo "$GITHUB_REPO" | sed -E 's#^https?://##')"
else
  GIT_AUTH_REPO="$GITHUB_REPO"
fi

# Initial startup message
log "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
log "$COLOR_GREEN" "⚙️ Configuration:"
log "$COLOR_GREEN" "   - GitHub Repo: $GITHUB_REPO"
log "$COLOR_GREEN" "   - Dry run: $DRY_RUN"
log "$COLOR_GREEN" "   - Skip push: $SKIP_PUSH"

# Run update check
perform_update_check

log "$COLOR_PURPLE" "✨ Updater finished successfully"