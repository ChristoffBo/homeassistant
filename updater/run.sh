#!/bin/bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/tmp/addon-updater.lock"
BACKUP_DIR="/tmp/addon-backups"

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
declare -A FAILED_ADDONS
declare -a SKIP_LIST=()
PULL_STATUS=""
PUSH_STATUS=""
MAX_RETRIES=3
RETRY_DELAY=2
CURL_TIMEOUT=10
PARALLEL_JOBS=4

# ======================
# LOCK MANAGEMENT
# ======================
acquire_lock() {
  local max_wait=300
  local waited=0
  
  while [ $waited -lt $max_wait ]; do
    if mkdir "$LOCK_FILE" 2>/dev/null; then
      trap 'release_lock' EXIT INT TERM
      echo $$ > "$LOCK_FILE/pid"
      return 0
    fi
    
    # Check if lock is stale (process no longer exists)
    if [ -f "$LOCK_FILE/pid" ]; then
      local lock_pid
      lock_pid=$(cat "$LOCK_FILE/pid" 2>/dev/null || echo "")
      if [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
        log "$COLOR_YELLOW" "⚠️ Removing stale lock from PID $lock_pid"
        release_lock
        continue
      fi
    fi
    
    sleep 2
    waited=$((waited + 2))
  done
  
  log "$COLOR_RED" "❌ Failed to acquire lock after ${max_wait}s"
  return 1
}

release_lock() {
  rm -rf "$LOCK_FILE" 2>/dev/null || true
}

# ======================
# HELPER FUNCTIONS
# ======================
safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]][[:alnum:].:_-]*$' || echo "unknown"
}

read_config() {
  TZ=$(jq -er '.timezone // "UTC"' "$CONFIG_PATH" 2>/dev/null || echo "UTC")
  export TZ

  DRY_RUN=$(jq -er '.dry_run // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  DEBUG=$(jq -er '.debug // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  SKIP_PUSH=$(jq -er '.skip_push // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  
  mapfile -t SKIP_LIST < <(jq -er '.skip_addons[]?' "$CONFIG_PATH" 2>/dev/null || true)

  NOTIFY_ENABLED=$(jq -er '.enable_notifications // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  NOTIFY_SERVICE=$(jq -er '.notification_service // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_URL=$(jq -er '.notification_url // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TOKEN=$(jq -er '.notification_token // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_TO=$(jq -er '.notification_to // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
  NOTIFY_SUCCESS=$(jq -er '.notify_on_success // false' "$CONFIG_PATH" 2>/dev/null || echo "false")
  NOTIFY_ERROR=$(jq -er '.notify_on_error // true' "$CONFIG_PATH" 2>/dev/null || echo "true")
  NOTIFY_UPDATES=$(jq -er '.notify_on_updates // true' "$CONFIG_PATH" 2>/dev/null || echo "true")

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

  # Sanitize repo URL for auth (prevent credential leakage)
  GIT_AUTH_REPO="$GIT_REPO"
  if [ -n "$GIT_USER" ] && [ -n "$GIT_TOKEN" ]; then
    GIT_AUTH_REPO="${GIT_REPO/https:\/\//https://$GIT_USER:$GIT_TOKEN@}"
  fi
  
  # Read optional performance tuning
  PARALLEL_JOBS=$(jq -er '.parallel_jobs // 4' "$CONFIG_PATH" 2>/dev/null || echo "4")
  CURL_TIMEOUT=$(jq -er '.curl_timeout // 10' "$CONFIG_PATH" 2>/dev/null || echo "10")
}

log() {
  local color="$1"; shift
  local level="${1:-INFO}"
  shift || true
  
  # Sanitize log output to prevent credential leakage
  local message="$*"
  if [ -n "$GIT_TOKEN" ]; then
    message="${message//$GIT_TOKEN/***TOKEN***}"
  fi
  
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}[${level}]${COLOR_RESET} ${message}" | tee -a "$LOG_FILE"
  
  [ "$DEBUG" = "true" ] && echo "[DEBUG] $*" >> "$LOG_FILE.debug"
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
    
    if ! curl -s -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" \
         -H "Content-Type: application/json" \
         -d "$payload" \
         --max-time 10 > /dev/null 2>&1; then
      log "$COLOR_RED" "ERROR" "Gotify notification failed"
    fi
  fi
}

# ======================
# RETRY WRAPPER
# ======================
retry_command() {
  local max_attempts="$1"
  shift
  local attempt=1
  local delay="$RETRY_DELAY"
  
  while [ $attempt -le $max_attempts ]; do
    if "$@"; then
      return 0
    fi
    
    if [ $attempt -lt $max_attempts ]; then
      log "$COLOR_YELLOW" "WARN" "Command failed (attempt $attempt/$max_attempts), retrying in ${delay}s..."
      sleep "$delay"
      delay=$((delay * 2))
    fi
    
    attempt=$((attempt + 1))
  done
  
  log "$COLOR_RED" "ERROR" "Command failed after $max_attempts attempts"
  return 1
}

# ======================
# VERSION VALIDATION
# ======================
validate_version() {
  local version="$1"
  
  # Validate version format (semver-like)
  if ! echo "$version" | grep -qE '^[vV]?[0-9]+(\.[0-9]+){0,3}(-[a-zA-Z0-9]+)?$'; then
    log "$COLOR_RED" "ERROR" "Invalid version format: $version"
    return 1
  fi
  
  # Reject suspicious versions
  if echo "$version" | grep -qiE '(latest|dev|test|debug|alpha|beta|rc[0-9]*)$'; then
    log "$COLOR_YELLOW" "WARN" "Suspicious version tag: $version"
    return 1
  fi
  
  return 0
}

# ======================
# TAG FETCHING WITH RETRY
# ======================
get_latest_tag() {
  local image="$1"
  [ -z "$image" ] && return

  local arch
  arch=$(uname -m)
  arch=${arch//x86_64/amd64}
  arch=${arch//aarch64/arm64}
  image="${image//\{arch\}/$arch}"
  local image_name="${image%%:*}"
  local cache_file="/tmp/tags_$(echo "$image_name" | tr '/' '_').txt"

  # Use cached result if fresh (4 hours)
  if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || echo 0))) -lt 14400 ]; then
    cat "$cache_file"
    return
  fi

  local tags=""
  local ns_repo="${image_name/library\//}"

  # Docker Hub with retry
  if [ -z "$tags" ]; then
    local page=1
    while [ $page -le 5 ]; do
      local result
      if result=$(retry_command 2 curl -sf --max-time "$CURL_TIMEOUT" \
                  "https://hub.docker.com/v2/repositories/$ns_repo/tags?page=$page&page_size=100"); then
        local page_tags
        page_tags=$(echo "$result" | jq -r '.results[].name' 2>/dev/null || echo "")
        [ -z "$page_tags" ] && break
        tags="$tags
$page_tags"
        [ "$(echo "$result" | jq -r '.next')" = "null" ] && break
        page=$((page + 1))
      else
        break
      fi
    done
  fi

  # lscr.io with retry
  if [ -z "$tags" ]; then
    if result=$(retry_command 2 curl -sf --max-time "$CURL_TIMEOUT" \
                "https://fleet.linuxserver.io/image?name=${image_name##*/}"); then
      tags=$(echo "$result" | jq -r '.platforms."linux/amd64".lastUpdated.tag' 2>/dev/null || echo "")
    fi
  fi

  # ghcr.io with retry
  if [ -z "$tags" ] && echo "$image_name" | grep -q "^ghcr.io/"; then
    local path="${image_name#ghcr.io/}"
    local org_repo="${path%%/*}"
    local package="${path#*/}"
    
    local token
    if token=$(retry_command 2 curl -sf --max-time "$CURL_TIMEOUT" \
               "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token'); then
      if [ -n "$token" ] && [ "$token" != "null" ]; then
        tags=$(retry_command 2 curl -sf --max-time "$CURL_TIMEOUT" \
               -H "Authorization: Bearer $token" \
               "https://ghcr.io/v2/$org_repo/$package/tags/list" | jq -r '.tags[]?' 2>/dev/null || echo "")
      fi
    fi
  fi

  # Filter and validate
  local latest
  latest=$(echo "$tags" | grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}(-[a-z0-9]+)?$' | \
           grep -viE 'latest|dev|rc|beta|alpha' | \
           sort -Vr | head -n1)
  
  if [ -n "$latest" ] && validate_version "$latest"; then
    echo "$latest" | tee "$cache_file"
  fi
}

# ======================
# BACKUP MANAGEMENT
# ======================
backup_addon() {
  local addon_path="$1"
  local name
  name=$(basename "$addon_path")
  local backup_path="$BACKUP_DIR/$name"
  
  mkdir -p "$backup_path"
  cp -f "$addon_path/config.json" "$backup_path/config.json.bak" 2>/dev/null || true
  [ -f "$addon_path/build.json" ] && cp -f "$addon_path/build.json" "$backup_path/build.json.bak" 2>/dev/null || true
  [ -f "$addon_path/CHANGELOG.md" ] && cp -f "$addon_path/CHANGELOG.md" "$backup_path/CHANGELOG.md.bak" 2>/dev/null || true
}

restore_addon() {
  local addon_path="$1"
  local name
  name=$(basename "$addon_path")
  local backup_path="$BACKUP_DIR/$name"
  
  if [ -d "$backup_path" ]; then
    [ -f "$backup_path/config.json.bak" ] && cp -f "$backup_path/config.json.bak" "$addon_path/config.json"
    [ -f "$backup_path/build.json.bak" ] && cp -f "$backup_path/build.json.bak" "$addon_path/build.json"
    [ -f "$backup_path/CHANGELOG.md.bak" ] && cp -f "$backup_path/CHANGELOG.md.bak" "$addon_path/CHANGELOG.md"
    log "$COLOR_YELLOW" "WARN" "Restored backup for $name"
  fi
}

# ======================
# ADDON UPDATE LOGIC
# ======================
update_addon() {
  local addon_path="$1"
  local name
  name=$(basename "$addon_path")

  for skip in "${SKIP_LIST[@]}"; do
    [ "$name" = "$skip" ] && log "$COLOR_YELLOW" "INFO" "⏭️ Skipping $name (listed)" && return 0
  done

  log "$COLOR_DARK_BLUE" "INFO" "🔍 Checking $name"

  local config="$addon_path/config.json"
  local build="$addon_path/build.json"
  local image version latest

  image=$(jq -r '.image // empty' "$config" 2>/dev/null || echo "")
  version=$(safe_jq '.version' "$config")

  if [ -z "$image" ] && [ -f "$build" ]; then
    image=$(jq -r '.build_from.amd64 // .build_from | strings' "$build" 2>/dev/null || echo "")
    version=$(safe_jq '.version' "$build")
  fi

  if [ -z "$image" ]; then
    log "$COLOR_YELLOW" "WARN" "⚠️ No image defined for $name"
    UNCHANGED_ADDONS["$name"]="No image defined"
    return 0
  fi

  latest=$(get_latest_tag "$image")
  if [ -z "$latest" ]; then
    log "$COLOR_YELLOW" "WARN" "⚠️ No valid version tag found for $image"
    UNCHANGED_ADDONS["$name"]="No valid tag"
    return 0
  fi

  if [ "$version" != "$latest" ]; then
    log "$COLOR_GREEN" "INFO" "⬆️ $name updated from $version to $latest"
    UPDATED_ADDONS["$name"]="$version → $latest"

    if [ "$DRY_RUN" = "true" ]; then
      log "$COLOR_PURPLE" "INFO" "💡 Dry run active: skipping update of $name"
      return 0
    fi

    # Backup before updating
    backup_addon "$addon_path"

    # Atomic file operations with rollback on failure
    if ! jq --arg v "$latest" '.version = $v' "$config" > "$config.tmp"; then
      log "$COLOR_RED" "ERROR" "❌ Failed to update $config"
      rm -f "$config.tmp"
      restore_addon "$addon_path"
      FAILED_ADDONS["$name"]="Config update failed"
      return 1
    fi
    
    if ! mv "$config.tmp" "$config"; then
      log "$COLOR_RED" "ERROR" "❌ Failed to write $config"
      restore_addon "$addon_path"
      FAILED_ADDONS["$name"]="Config write failed"
      return 1
    fi
    
    if [ -f "$build" ]; then
      if ! jq --arg v "$latest" '.version = $v' "$build" > "$build.tmp"; then
        log "$COLOR_RED" "ERROR" "❌ Failed to update $build"
        rm -f "$build.tmp"
        restore_addon "$addon_path"
        FAILED_ADDONS["$name"]="Build update failed"
        return 1
      fi
      
      if ! mv "$build.tmp" "$build"; then
        log "$COLOR_RED" "ERROR" "❌ Failed to write $build"
        restore_addon "$addon_path"
        FAILED_ADDONS["$name"]="Build write failed"
        return 1
      fi
    fi

    # Update changelog
    local changelog="$addon_path/CHANGELOG.md"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local docker_img="${image%%:*}:$latest"
    local image_url

    if [[ "$image" == ghcr.io/* ]]; then
      image_url="https://github.com/orgs/${image#ghcr.io/}/packages"
    elif [[ "$image" == *"lscr.io"* || "$image" == *"linuxserver"* ]]; then
      local image_name_clean="${image_name##*/}"
      image_url="https://fleet.linuxserver.io/image?name=${image_name_clean}"
    else
      image_url="https://hub.docker.com/r/${image%%:*}/tags"
    fi

    if [ -f "$changelog" ]; then
      {
        echo "## $latest ($timestamp)"
        echo "- Update from $version to $latest"
        echo "- Docker Image: [$docker_img]($image_url)"
        echo
        cat "$changelog"
      } > "$changelog.tmp"
      
      if [ -s "$changelog.tmp" ]; then
        mv "$changelog.tmp" "$changelog"
      else
        log "$COLOR_RED" "ERROR" "❌ Failed to update changelog for $name"
        rm -f "$changelog.tmp"
        restore_addon "$addon_path"
        FAILED_ADDONS["$name"]="Changelog update failed"
        return 1
      fi
    else
      {
        echo "# Changelog"
        echo
        echo "## $latest ($timestamp)"
        echo "- Update from $version to $latest"
        echo "- Docker Image: [$docker_img]($image_url)"
        echo
      } > "$changelog"
    fi
  else
    log "$COLOR_CYAN" "INFO" "✅ $name is up to date ($version)"
    UNCHANGED_ADDONS["$name"]="Up to date ($version)"
  fi
  
  return 0
}

# ======================
# GIT OPERATIONS
# ======================
commit_and_push() {
  cd "$REPO_DIR" || {
    log "$COLOR_RED" "ERROR" "❌ Failed to change to repo directory"
    return 1
  }
  
  git config user.email "updater@local"
  git config user.name "Add-on Updater"

  if retry_command "$MAX_RETRIES" git pull --rebase; then
    PULL_STATUS="✅ Git pull (rebase) succeeded"
    log "$COLOR_GREEN" "INFO" "$PULL_STATUS"
  else
    PULL_STATUS="❌ Git pull (rebase) failed"
    log "$COLOR_RED" "ERROR" "$PULL_STATUS"
    return 1
  fi

  if [ -n "$(git status --porcelain)" ]; then
    local commit_msg="🔄 Updated add-on versions"
    
    # Add details to commit message
    if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
      commit_msg="$commit_msg

Updated addons:"
      for addon in "${!UPDATED_ADDONS[@]}"; do
        commit_msg="$commit_msg
- $addon: ${UPDATED_ADDONS[$addon]}"
      done
    fi
    
    if git add . && git commit -m "$commit_msg"; then
      log "$COLOR_GREEN" "INFO" "✅ Changes committed successfully"
    else
      log "$COLOR_RED" "ERROR" "❌ Failed to commit changes"
      return 1
    fi
    
    if [ "$SKIP_PUSH" = "true" ]; then
      PUSH_STATUS="⏭️ Git push skipped (skip_push enabled)"
      log "$COLOR_YELLOW" "INFO" "$PUSH_STATUS"
    elif retry_command "$MAX_RETRIES" git push "$GIT_AUTH_REPO" main; then
      PUSH_STATUS="✅ Git push succeeded"
      log "$COLOR_GREEN" "INFO" "$PUSH_STATUS"
    else
      log "$COLOR_RED" "ERROR" "❌ Git push failed"
      PUSH_STATUS="❌ Git push failed"
      return 1
    fi
  else
    PUSH_STATUS="ℹ️ No changes to commit or push"
    log "$COLOR_CYAN" "INFO" "$PUSH_STATUS"
  fi
  
  return 0
}

# ======================
# PARALLEL PROCESSING
# ======================
process_addons_parallel() {
  local temp_dir="$1"
  local pids=()
  local count=0
  
  for path in "$REPO_DIR"/*; do
    [ ! -d "$path" ] && continue
    
    # Run in background with job control
    (update_addon "$path") &
    pids+=($!)
    count=$((count + 1))
    
    # Limit concurrent jobs
    if [ $count -ge "$PARALLEL_JOBS" ]; then
      wait "${pids[@]}"
      pids=()
      count=0
    fi
  done
  
  # Wait for remaining jobs
  [ ${#pids[@]} -gt 0 ] && wait "${pids[@]}"
}

# ======================
# MAIN LOGIC
# ======================
main() {
  # Initialize log
  : > "$LOG_FILE"
  
  # Acquire lock
  if ! acquire_lock; then
    log "$COLOR_RED" "ERROR" "❌ Another instance is running"
    exit 1
  fi
  
  read_config
  log "$COLOR_BLUE" "INFO" "ℹ️ Starting Home Assistant Add-on Updater"
  log "$COLOR_BLUE" "INFO" "ℹ️ Parallel jobs: $PARALLEL_JOBS, Curl timeout: ${CURL_TIMEOUT}s"

  # Setup temp and backup directories
  local temp_dir
  temp_dir=$(mktemp -d) || temp_dir="/tmp/updater_$$"
  mkdir -p "$BACKUP_DIR"
  
  cd "$temp_dir" || {
    log "$COLOR_RED" "ERROR" "❌ Failed to change to temporary directory"
    exit 1
  }
  
  [ -d "$REPO_DIR" ] && rm -rf "$REPO_DIR"

  if ! retry_command "$MAX_RETRIES" git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR"; then
    log "$COLOR_RED" "ERROR" "❌ Git clone failed after retries"
    notify "Updater Error" "Git clone failed after $MAX_RETRIES attempts" 5
    exit 1
  fi

  # Process addons (parallel if enabled)
  if [ "$PARALLEL_JOBS" -gt 1 ]; then
    log "$COLOR_BLUE" "INFO" "ℹ️ Processing addons in parallel (jobs: $PARALLEL_JOBS)"
    process_addons_parallel "$temp_dir"
  else
    for path in "$REPO_DIR"/*; do
      [ -d "$path" ] && update_addon "$path"
    done
  fi

  # Commit and push changes
  if ! commit_and_push; then
    log "$COLOR_RED" "ERROR" "❌ Git operations failed"
    notify "Updater Error" "Git commit/push failed" 5
  fi

  # Generate summary
  local summary="📦 Add-on Update Summary
🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')

"

  if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
    summary+="🔄 Updated (${#UPDATED_ADDONS[@]}):\n"
    for name in "${!UPDATED_ADDONS[@]}"; do
      summary+="  • $name: ${UPDATED_ADDONS[$name]}
"
    done
    summary+="
"
  fi
  
  if [ ${#FAILED_ADDONS[@]} -gt 0 ]; then
    summary+="❌ Failed (${#FAILED_ADDONS[@]}):\n"
    for name in "${!FAILED_ADDONS[@]}"; do
      summary+="  • $name: ${FAILED_ADDONS[$name]}
"
    done
    summary+="
"
  fi

  if [ ${#UNCHANGED_ADDONS[@]} -gt 0 ]; then
    summary+="✅ Unchanged (${#UNCHANGED_ADDONS[@]}):\n"
    for name in "${!UNCHANGED_ADDONS[@]}"; do
      summary+="  • $name: ${UNCHANGED_ADDONS[$name]}
"
    done
    summary+="
"
  fi

  [ -n "$PULL_STATUS" ] && summary+="
$PULL_STATUS"
  [ -n "$PUSH_STATUS" ] && summary+="
$PUSH_STATUS"
  [ "$DRY_RUN" = "true" ] && summary+="
🔁 DRY RUN MODE ENABLED"

  # Determine notification priority
  local notify_priority=3
  [ ${#FAILED_ADDONS[@]} -gt 0 ] && notify_priority=5
  [ ${#UPDATED_ADDONS[@]} -eq 0 ] && [ ${#FAILED_ADDONS[@]} -eq 0 ] && notify_priority=0

  notify "Add-on Updater" "$summary" "$notify_priority"
  log "$COLOR_BLUE" "INFO" "ℹ️ Update process complete."
  echo -e "\n$summary" | tee -a "$LOG_FILE"
  
  # Cleanup
  cd / && rm -rf "$temp_dir" "$BACKUP_DIR" 2>/dev/null || true
}

main "$@"
