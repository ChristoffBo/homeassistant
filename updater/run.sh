#!/bin/bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
CACHE_DIR="/tmp/addon_updater_cache"
MAX_PARALLEL_JOBS=5

# ======================
# COLOR DEFINITIONS
# ======================
readonly COLOR_RESET="\033[0m"
readonly COLOR_GREEN="\033[0;32m"
readonly COLOR_BLUE="\033[0;34m"
readonly COLOR_DARK_BLUE="\033[0;94m"
readonly COLOR_YELLOW="\033[0;33m"
readonly COLOR_RED="\033[0;31m"
readonly COLOR_PURPLE="\033[0;35m"
readonly COLOR_CYAN="\033[0;36m"

# ======================
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS
declare -A ADDON_STATUS
declare -a SKIP_LIST=()
declare -A API_TOKENS=()
PULL_STATUS=""
PUSH_STATUS=""

# Performance optimization: Create cache directory
mkdir -p "$CACHE_DIR"

# Optimized safe_jq with better error handling
safe_jq() {
  local expr="$1"
  local file="$2"
  local default="${3:-unknown}"
  
  if [[ ! -f "$file" ]]; then
    echo "$default"
    return
  fi
  
  local result
  result=$(jq -e -r "$expr" "$file" 2>/dev/null || echo "$default")
  
  # Validate the result format for version strings
  if [[ "$expr" == *"version"* ]] && [[ "$result" =~ ^[[:alnum:]][[:alnum:].:_-]*$ ]]; then
    echo "$result"
  elif [[ "$expr" != *"version"* ]]; then
    echo "$result"
  else
    echo "$default"
  fi
}

read_config() {
  local config_cache="$CACHE_DIR/config_cache"
  
  # Cache config reading to avoid repeated jq calls
  if [[ -f "$config_cache" ]] && [[ "$CONFIG_PATH" -ot "$config_cache" ]]; then
    source "$config_cache"
    return
  fi
  
  # Read all config at once for better performance
  local config_json
  config_json=$(cat "$CONFIG_PATH" 2>/dev/null || echo '{}')
  
  TZ=$(echo "$config_json" | jq -er '.timezone // "UTC"' 2>/dev/null || echo "UTC")
  export TZ

  DRY_RUN=$(echo "$config_json" | jq -er '.dry_run // false' 2>/dev/null || echo "false")
  DEBUG=$(echo "$config_json" | jq -er '.debug // false' 2>/dev/null || echo "false")
  SKIP_PUSH=$(echo "$config_json" | jq -er '.skip_push // false' 2>/dev/null || echo "false")
  
  # Optimized array reading
  mapfile -t SKIP_LIST < <(echo "$config_json" | jq -er '.skip_addons[]?' 2>/dev/null || true)

  NOTIFY_ENABLED=$(echo "$config_json" | jq -er '.enable_notifications // false' 2>/dev/null || echo "false")
  NOTIFY_SERVICE=$(echo "$config_json" | jq -er '.notification_service // ""' 2>/dev/null || echo "")
  NOTIFY_URL=$(echo "$config_json" | jq -er '.notification_url // ""' 2>/dev/null || echo "")
  NOTIFY_TOKEN=$(echo "$config_json" | jq -er '.notification_token // ""' 2>/dev/null || echo "")
  NOTIFY_TO=$(echo "$config_json" | jq -er '.notification_to // ""' 2>/dev/null || echo "")
  NOTIFY_SUCCESS=$(echo "$config_json" | jq -er '.notify_on_success // false' 2>/dev/null || echo "false")
  NOTIFY_ERROR=$(echo "$config_json" | jq -er '.notify_on_error // true' 2>/dev/null || echo "true")
  NOTIFY_UPDATES=$(echo "$config_json" | jq -er '.notify_on_updates // true' 2>/dev/null || echo "true")

  GIT_PROVIDER=$(echo "$config_json" | jq -er '.git_provider // "github"' 2>/dev/null || echo "github")

  if [[ "$GIT_PROVIDER" == "gitea" ]]; then
    GIT_REPO=$(echo "$config_json" | jq -er '.gitea_repository' 2>/dev/null || echo "")
    GIT_USER=$(echo "$config_json" | jq -er '.gitea_username' 2>/dev/null || echo "")
    GIT_TOKEN=$(echo "$config_json" | jq -er '.gitea_token' 2>/dev/null || echo "")
  else
    GIT_REPO=$(echo "$config_json" | jq -er '.github_repository' 2>/dev/null || echo "")
    GIT_USER=$(echo "$config_json" | jq -er '.github_username' 2>/dev/null || echo "")
    GIT_TOKEN=$(echo "$config_json" | jq -er '.github_token' 2>/dev/null || echo "")
  fi

  GIT_AUTH_REPO="$GIT_REPO"
  if [[ -n "$GIT_USER" && -n "$GIT_TOKEN" ]]; then
    GIT_AUTH_REPO="${GIT_REPO/https:\/\//https://$GIT_USER:$GIT_TOKEN@}"
  fi
  
  # Cache the config variables for next run
  {
    echo "TZ='$TZ'"
    echo "DRY_RUN='$DRY_RUN'"
    echo "DEBUG='$DEBUG'"
    echo "SKIP_PUSH='$SKIP_PUSH'"
    echo "NOTIFY_ENABLED='$NOTIFY_ENABLED'"
    echo "NOTIFY_SERVICE='$NOTIFY_SERVICE'"
    echo "NOTIFY_URL='$NOTIFY_URL'"
    echo "NOTIFY_TOKEN='$NOTIFY_TOKEN'"
    echo "NOTIFY_SUCCESS='$NOTIFY_SUCCESS'"
    echo "NOTIFY_ERROR='$NOTIFY_ERROR'"
    echo "NOTIFY_UPDATES='$NOTIFY_UPDATES'"
    echo "GIT_PROVIDER='$GIT_PROVIDER'"
    echo "GIT_REPO='$GIT_REPO'"
    echo "GIT_USER='$GIT_USER'"
    echo "GIT_TOKEN='$GIT_TOKEN'"
    echo "GIT_AUTH_REPO='$GIT_AUTH_REPO'"
  } > "$config_cache"
}

log() {
  local color="$1"; shift
  local timestamp
  timestamp=$(date '+[%Y-%m-%d %H:%M:%S %Z]')
  echo -e "${timestamp} ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Asynchronous notification with retry
notify() {
  local title="$1"
  local message="$2"
  local priority="${3:-0}"

  [[ "$NOTIFY_ENABLED" != "true" ]] && return
  
  case "$priority" in
    0) [[ "$NOTIFY_SUCCESS" != "true" ]] && return ;;
    3) [[ "$NOTIFY_UPDATES" != "true" ]] && return ;;
    5) [[ "$NOTIFY_ERROR" != "true" ]] && return ;;
  esac

  if [[ "$NOTIFY_SERVICE" == "gotify" ]]; then
    local payload
    payload=$(jq -n --arg t "$title" --arg m "$message" --argjson p "$priority" \
      '{title: $t, message: $m, priority: $p}')
    
    # Asynchronous notification with retry
    (
      for i in {1..3}; do
        if curl -s --max-time 10 -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" \
           -H "Content-Type: application/json" -d "$payload" > /dev/null 2>&1; then
          break
        fi
        [[ $i -lt 3 ]] && sleep $((i * 2))
      done
    ) &
  fi
}

# Optimized Docker Hub API calls with pagination and caching
get_dockerhub_tags() {
  local repo="$1"
  local cache_file="$2"
  local tags=""
  
  # Use Docker Hub API v2 with improved error handling
  local page=1
  local max_pages=10  # Limit to prevent infinite loops
  
  while [[ $page -le $max_pages ]]; do
    local url="https://hub.docker.com/v2/repositories/$repo/tags?page=$page&page_size=100"
    local result
    
    if ! result=$(curl -sf --max-time 15 --retry 2 "$url" 2>/dev/null); then
      break
    fi
    
    local page_tags
    page_tags=$(echo "$result" | jq -r '.results[]?.name // empty' 2>/dev/null)
    
    [[ -z "$page_tags" ]] && break
    
    tags="$tags"$'\n'"$page_tags"
    
    # Check if there's a next page
    local next_url
    next_url=$(echo "$result" | jq -r '.next // empty' 2>/dev/null)
    [[ -z "$next_url" || "$next_url" == "null" ]] && break
    
    ((page++))
  done
  
  echo "$tags"
}

# Improved GHCR token caching and authentication
get_ghcr_token() {
  local org_repo="$1"
  local package="$2"
  local token_cache="$CACHE_DIR/ghcr_token_${org_repo//\//_}_${package//\//_}"
  
  # Check cached token (valid for 1 hour)
  if [[ -f "$token_cache" ]] && [[ $(($(date +%s) - $(stat -c %Y "$token_cache" 2>/dev/null || echo 0))) -lt 3600 ]]; then
    cat "$token_cache"
    return
  fi
  
  local token
  if token=$(curl -sf --max-time 10 "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" 2>/dev/null | jq -r '.token // empty'); then
    [[ -n "$token" && "$token" != "null" ]] && echo "$token" | tee "$token_cache"
  fi
}

# Enhanced tag fetching with parallel processing and better registry support
get_latest_tag() {
  local image="$1"
  [[ -z "$image" ]] && return

  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64) arch="amd64" ;;
    aarch64) arch="arm64" ;;
    armv7l) arch="arm/v7" ;;
  esac
  
  image="${image//\{arch\}/$arch}"
  local image_name="${image%%:*}"
  local cache_file="$CACHE_DIR/tags_$(echo "$image_name" | tr '/' '_' | tr ':' '_').txt"

  # Check cache (4 hours TTL)
  if [[ -f "$cache_file" ]] && [[ $(($(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || echo 0))) -lt 14400 ]]; then
    cat "$cache_file"
    return
  fi

  local tags=""
  local registry=""
  
  # Determine registry and optimize API calls
  if [[ "$image_name" == ghcr.io/* ]]; then
    registry="ghcr"
    local path="${image_name#ghcr.io/}"
    local org_repo="${path%%/*}"
    local package="${path#*/}"
    
    local token
    token=$(get_ghcr_token "$org_repo" "$package")
    
    if [[ -n "$token" ]]; then
      tags=$(curl -sf --max-time 15 --retry 2 \
        -H "Authorization: Bearer $token" \
        "https://ghcr.io/v2/$org_repo/$package/tags/list" 2>/dev/null | \
        jq -r '.tags[]? // empty' 2>/dev/null)
    fi
  elif [[ "$image_name" == *"lscr.io"* || "$image_name" == *"linuxserver"* ]]; then
    registry="linuxserver"
    local package_name="${image_name##*/}"
    tags=$(curl -sf --max-time 15 --retry 2 \
      "https://fleet.linuxserver.io/api/v1/images/$package_name" 2>/dev/null | \
      jq -r '.available_architectures.amd64[]?.tag_name // empty' 2>/dev/null)
  else
    registry="dockerhub"
    local ns_repo="${image_name#docker.io/}"
    ns_repo="${ns_repo/library\//}"
    tags=$(get_dockerhub_tags "$ns_repo" "$cache_file")
  fi

  # Enhanced version filtering with better regex and sorting
  local latest_tag
  latest_tag=$(echo "$tags" | \
    grep -E '^[vV]?[0-9]+(\.[0-9]+){0,3}(-[a-z0-9]+)*$' | \
    grep -viE 'latest|edge|dev|nightly|rc|alpha|beta|snapshot|test' | \
    sort -t. -k1,1nr -k2,2nr -k3,3nr -k4,4nr | \
    head -n1)
  
  [[ -n "$latest_tag" ]] && echo "$latest_tag" | tee "$cache_file"
}

# Parallel addon processing with job control
update_addon() {
  local addon_path="$1"
  local name
  name=$(basename "$addon_path")

  # Check skip list efficiently
  for skip in "${SKIP_LIST[@]}"; do
    if [[ "$name" == "$skip" ]]; then
      log "$COLOR_YELLOW" "⏭️ Skipping $name (listed)"
      ADDON_STATUS["$name"]="skipped"
      return
    fi
  done

  log "$COLOR_DARK_BLUE" "🔍 Checking $name"

  local config="$addon_path/config.json"
  local build="$addon_path/build.json"
  local dockerfile="$addon_path/Dockerfile"
  local image version latest

  # Optimized config reading
  if [[ -f "$config" ]]; then
    image=$(safe_jq '.image' "$config" "")
    version=$(safe_jq '.version' "$config")
  fi

  # Fallback to build.json
  if [[ -z "$image" && -f "$build" ]]; then
    image=$(safe_jq '.build_from.amd64 // .build_from' "$build" "")
    version=$(safe_jq '.version' "$build")
  fi

  # Fallback to Dockerfile FROM instruction
  if [[ -z "$image" && -f "$dockerfile" ]]; then
    image=$(grep -m1 '^FROM ' "$dockerfile" 2>/dev/null | awk '{print $2}' || echo "")
  fi

  if [[ -z "$image" ]]; then
    log "$COLOR_YELLOW" "⚠️ No image defined for $name"
    UNCHANGED_ADDONS["$name"]="No image defined"
    ADDON_STATUS["$name"]="no_image"
    return
  fi

  # Get latest version with timeout and better error handling
  local latest
  if ! latest=$(timeout 60 bash -c "get_latest_tag '$image'" 2>/dev/null); then
    log "$COLOR_YELLOW" "⚠️ Timeout or error getting version for $image"
    UNCHANGED_ADDONS["$name"]="Version check failed"
    ADDON_STATUS["$name"]="timeout"
    return
  fi

  if [[ -z "$latest" ]]; then
    log "$COLOR_YELLOW" "⚠️ No valid version tag found for $image"
    UNCHANGED_ADDONS["$name"]="No valid tag"
    ADDON_STATUS["$name"]="no_tag"
    return
  fi

  if [[ "$version" != "$latest" ]]; then
    log "$COLOR_GREEN" "⬆️ $name updated from $version to $latest"
    UPDATED_ADDONS["$name"]="$version → $latest"
    ADDON_STATUS["$name"]="updated"

    if [[ "$DRY_RUN" == "true" ]]; then
      log "$COLOR_PURPLE" "💡 Dry run active: skipping update of $name"
      return
    fi

    # Atomic file updates with validation
    update_config_files "$addon_path" "$latest" "$name" "$image" "$version"
  else
    log "$COLOR_CYAN" "✅ $name is up to date ($version)"
    UNCHANGED_ADDONS["$name"]="Up to date ($version)"
    ADDON_STATUS["$name"]="current"
  fi
}

# Separated config file updates for better maintainability
update_config_files() {
  local addon_path="$1"
  local latest="$2"
  local name="$3"
  local image="$4"
  local version="$5"
  
  local config="$addon_path/config.json"
  local build="$addon_path/build.json"
  
  # Update config.json
  if [[ -f "$config" ]]; then
    local temp_config
    temp_config=$(mktemp)
    if jq --arg v "$latest" '.version = $v' "$config" > "$temp_config" 2>/dev/null && [[ -s "$temp_config" ]]; then
      mv "$temp_config" "$config"
    else
      log "$COLOR_RED" "❌ Failed to update $config"
      rm -f "$temp_config"
      return 1
    fi
  fi
  
  # Update build.json
  if [[ -f "$build" ]]; then
    local temp_build
    temp_build=$(mktemp)
    if jq --arg v "$latest" '.version = $v' "$build" > "$temp_build" 2>/dev/null && [[ -s "$temp_build" ]]; then
      mv "$temp_build" "$build"
    else
      log "$COLOR_RED" "❌ Failed to update $build"
      rm -f "$temp_build"
      return 1
    fi
  fi

  # Update changelog
  update_changelog "$addon_path" "$latest" "$name" "$image" "$version"
}

# Optimized changelog updates
update_changelog() {
  local addon_path="$1"
  local latest="$2"
  local name="$3"
  local image="$4"
  local version="$5"
  
  local changelog="$addon_path/CHANGELOG.md"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  local docker_img="${image%%:*}:$latest"
  local image_url

  # Generate appropriate URLs based on registry
  case "$image" in
    ghcr.io/*)
      image_url="https://github.com/orgs/${image#ghcr.io/}/packages"
      ;;
    *lscr.io*|*linuxserver*)
      local image_name_clean="${image##*/}"
      image_url="https://fleet.linuxserver.io/image?name=${image_name_clean%%:*}"
      ;;
    *)
      image_url="https://hub.docker.com/r/${image%%:*}/tags"
      ;;
  esac

  # Create or update changelog atomically
  local temp_changelog
  temp_changelog=$(mktemp)
  
  {
    echo "## $latest ($timestamp)"
    echo "- Update from $version to $latest"
    echo "- Docker Image: [$docker_img]($image_url)"
    echo ""
    
    if [[ -f "$changelog" ]]; then
      cat "$changelog"
    else
      echo "# Changelog"
      echo ""
      echo "All notable changes to this add-on will be documented in this file."
      echo ""
    fi
  } > "$temp_changelog"
  
  if [[ -s "$temp_changelog" ]]; then
    mv "$temp_changelog" "$changelog"
  else
    log "$COLOR_RED" "❌ Failed to update changelog for $name"
    rm -f "$temp_changelog"
    return 1
  fi
}

# Optimized git operations with better error handling
commit_and_push() {
  local repo_dir="$1"
  cd "$repo_dir" || {
    log "$COLOR_RED" "❌ Failed to change to repo directory"
    return 1
  }
  
  # Configure git with better settings
  git config user.email "updater@homeassistant.local"
  git config user.name "HA Add-on Updater"
  git config pull.rebase true
  git config push.default simple
  
  # Detect current branch name
  local current_branch
  current_branch=$(git branch --show-current 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")

  # Check for changes first
  if [[ -z "$(git status --porcelain)" ]]; then
    PUSH_STATUS="ℹ️ No changes to commit or push"
    log "$COLOR_CYAN" "$PUSH_STATUS"
    return 0
  fi

  # Optimized pull with conflict resolution
  if git pull --rebase --autostash; then
    PULL_STATUS="✅ Git pull (rebase) succeeded"
    log "$COLOR_GREEN" "$PULL_STATUS"
  else
    PULL_STATUS="❌ Git pull (rebase) failed"
    log "$COLOR_RED" "$PULL_STATUS"
    # Try to abort rebase and continue
    git rebase --abort 2>/dev/null || true
  fi

  # Stage and commit changes
  git add .
  local commit_msg="🔄 Update add-on versions"
  
  # Add summary to commit message
  local update_count=${#UPDATED_ADDONS[@]}
  if [[ $update_count -gt 0 ]]; then
    commit_msg="$commit_msg

Updated $update_count add-on(s):"
    for addon in "${!UPDATED_ADDONS[@]}"; do
      commit_msg="$commit_msg
- $addon: ${UPDATED_ADDONS[$addon]}"
    done
  fi
  
  if git commit -m "$commit_msg"; then
    log "$COLOR_GREEN" "✅ Changes committed successfully"
  else
    log "$COLOR_RED" "❌ Failed to commit changes"
    return 1
  fi
  
  # Push changes to the correct branch
  if [[ "$SKIP_PUSH" == "true" ]]; then
    PUSH_STATUS="⏭️ Git push skipped (skip_push enabled)"
    log "$COLOR_YELLOW" "$PUSH_STATUS"
  else
    local push_attempts=3
    for ((i=1; i<=push_attempts; i++)); do
      if git push "$GIT_AUTH_REPO" "$current_branch"; then
        PUSH_STATUS="✅ Git push succeeded to branch '$current_branch'"
        log "$COLOR_GREEN" "$PUSH_STATUS"
        return 0
      else
        log "$COLOR_YELLOW" "⚠️ Git push attempt $i failed for branch '$current_branch'"
        [[ $i -lt $push_attempts ]] && sleep $((i * 2))
      fi
    done
    
    log "$COLOR_RED" "❌ Git push failed after $push_attempts attempts"
    PUSH_STATUS="❌ Git push failed after $push_attempts attempts"
    return 1
  fi
}

# Enhanced parallel processing with job control and better resource management
process_addons_parallel() {
  local repo_dir="$1"
  local -a addon_paths=()
  
  # Collect addon directories
  for path in "$repo_dir"/*; do
    [[ -d "$path" && -f "$path/config.json" ]] && addon_paths+=("$path")
  done
  
  local total_addons=${#addon_paths[@]}
  log "$COLOR_BLUE" "📦 Processing $total_addons add-ons with up to $MAX_PARALLEL_JOBS parallel jobs"
  
  # Reduce parallel jobs if system is under stress
  local load_avg
  load_avg=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo "0")
  if (( $(echo "$load_avg > 2.0" | bc -l 2>/dev/null || echo "0") )); then
    MAX_PARALLEL_JOBS=2
    log "$COLOR_YELLOW" "⚠️ High system load detected ($load_avg), reducing parallel jobs to $MAX_PARALLEL_JOBS"
  fi
  
  # Process addons in parallel batches with better job management
  local job_count=0
  local -a pids=()
  local -a job_names=()
  
  for addon_path in "${addon_paths[@]}"; do
    local addon_name
    addon_name=$(basename "$addon_path")
    
    # Wait for available slot with timeout protection
    local wait_cycles=0
    while [[ ${#pids[@]} -ge $MAX_PARALLEL_JOBS ]]; do
      # Check for completed jobs
      local new_pids=()
      local new_names=()
      
      for i in "${!pids[@]}"; do
        if ! kill -0 "${pids[$i]}" 2>/dev/null; then
          # Job completed
          wait "${pids[$i]}" 2>/dev/null || true
          log "$COLOR_CYAN" "✅ Completed processing ${job_names[$i]}"
        else
          new_pids+=("${pids[$i]}")
          new_names+=("${job_names[$i]}")
        fi
      done
      
      pids=("${new_pids[@]}")
      job_names=("${new_names[@]}")
      
      # Prevent infinite waiting
      if [[ ${#pids[@]} -ge $MAX_PARALLEL_JOBS ]]; then
        ((wait_cycles++))
        if [[ $wait_cycles -gt 300 ]]; then  # 30 seconds timeout
          log "$COLOR_YELLOW" "⚠️ Killing stuck jobs due to timeout"
          for pid in "${pids[@]}"; do
            kill -TERM "$pid" 2>/dev/null || true
          done
          sleep 2
          for pid in "${pids[@]}"; do
            kill -KILL "$pid" 2>/dev/null || true
          done
          pids=()
          job_names=()
          break
        fi
        sleep 0.1
      fi
    done
    
    # Start new job with timeout protection
    log "$COLOR_DARK_BLUE" "🚀 Starting processing of $addon_name"
    (
      # Set timeout for individual addon processing
      timeout 120 bash -c "update_addon '$addon_path'" || {
        log "$COLOR_RED" "❌ Timeout processing $addon_name"
        UNCHANGED_ADDONS["$addon_name"]="Processing timeout"
      }
    ) &
    
    pids+=($!)
    job_names+=("$addon_name")
    ((job_count++))
    
    # Small delay to prevent overwhelming the system
    sleep 0.05
  done
  
  # Wait for all remaining jobs with timeout
  log "$COLOR_BLUE" "⏳ Waiting for remaining ${#pids[@]} jobs to complete..."
  local remaining_wait=0
  
  while [[ ${#pids[@]} -gt 0 && $remaining_wait -lt 600 ]]; do  # 60 second timeout
    local new_pids=()
    local new_names=()
    
    for i in "${!pids[@]}"; do
      if ! kill -0 "${pids[$i]}" 2>/dev/null; then
        wait "${pids[$i]}" 2>/dev/null || true
        log "$COLOR_CYAN" "✅ Completed processing ${job_names[$i]}"
      else
        new_pids+=("${pids[$i]}")
        new_names+=("${job_names[$i]}")
      fi
    done
    
    pids=("${new_pids[@]}")
    job_names=("${new_names[@]}")
    
    if [[ ${#pids[@]} -gt 0 ]]; then
      sleep 1
      ((remaining_wait++))
    fi
  done
  
  # Kill any remaining stuck processes
  if [[ ${#pids[@]} -gt 0 ]]; then
    log "$COLOR_YELLOW" "⚠️ Terminating ${#pids[@]} remaining jobs due to timeout"
    for i in "${!pids[@]}"; do
      log "$COLOR_YELLOW" "⚠️ Killing stuck job: ${job_names[$i]}"
      kill -TERM "${pids[$i]}" 2>/dev/null || true
    done
    sleep 2
    for pid in "${pids[@]}"; do
      kill -KILL "$pid" 2>/dev/null || true
    done
  fi
  
  log "$COLOR_BLUE" "✅ Completed processing all $total_addons add-ons"
}

# Enhanced summary generation with statistics
generate_summary() {
  local summary="📦 Add-on Update Summary
🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')

📊 Statistics:
- Updated: ${#UPDATED_ADDONS[@]} add-ons
- Unchanged: ${#UNCHANGED_ADDONS[@]} add-ons
- Total processed: $((${#UPDATED_ADDONS[@]} + ${#UNCHANGED_ADDONS[@]}))

"

  # Group addons by status for better readability
  if [[ ${#UPDATED_ADDONS[@]} -gt 0 ]]; then
    summary+="🔄 Updated Add-ons:
"
    for addon in $(printf '%s\n' "${!UPDATED_ADDONS[@]}" | sort); do
      summary+="  • $addon: ${UPDATED_ADDONS[$addon]}
"
    done
    summary+="
"
  fi

  if [[ ${#UNCHANGED_ADDONS[@]} -gt 0 ]]; then
    summary+="✅ Unchanged Add-ons:
"
    for addon in $(printf '%s\n' "${!UNCHANGED_ADDONS[@]}" | sort); do
      summary+="  • $addon: ${UNCHANGED_ADDONS[$addon]}
"
    done
    summary+="
"
  fi

  [[ -n "$PULL_STATUS" ]] && summary+="$PULL_STATUS
"
  [[ -n "$PUSH_STATUS" ]] && summary+="$PUSH_STATUS
"
  [[ "$DRY_RUN" == "true" ]] && summary+="🔁 DRY RUN MODE ENABLED
"

  echo "$summary"
}

# Cleanup function for graceful shutdown
cleanup() {
  local exit_code="${1:-0}"
  log "$COLOR_BLUE" "🧹 Cleaning up..."
  
  # Kill any background jobs gracefully
  local pids
  pids=$(jobs -p 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    log "$COLOR_YELLOW" "⚠️ Terminating background jobs..."
    echo "$pids" | xargs -r kill -TERM 2>/dev/null || true
    sleep 2
    # Force kill if still running
    echo "$pids" | xargs -r kill -KILL 2>/dev/null || true
  fi
  
  # Clean old cache files (older than 24 hours) in background
  (find "$CACHE_DIR" -type f -mtime +1 -delete 2>/dev/null || true) &
  
  # Final summary if we have data
  if [[ ${#UPDATED_ADDONS[@]} -gt 0 || ${#UNCHANGED_ADDONS[@]} -gt 0 ]]; then
    local final_summary
    final_summary=$(generate_summary)
    log "$COLOR_BLUE" "📊 Final Summary:"
    echo "$final_summary"
  fi
  
  exit "$exit_code"
}

# Set up signal handlers
trap 'cleanup 130' INT TERM

main() {
  local start_time
  start_time=$(date +%s)
  
  # Initialize log
  echo "=== Home Assistant Add-on Updater Started ===" > "$LOG_FILE"
  
  read_config
  log "$COLOR_BLUE" "🚀 Starting Home Assistant Add-on Updater (Enhanced Version)"
  
  # Validate required configuration
  if [[ -z "$GIT_REPO" ]]; then
    log "$COLOR_RED" "❌ Git repository not configured"
    notify "Updater Error" "Git repository not configured" 5
    exit 1
  fi

  local temp_dir
  temp_dir=$(mktemp -d -t addon_updater.XXXXXX) || {
    log "$COLOR_RED" "❌ Failed to create temporary directory"
    exit 1
  }
  
  cd "$temp_dir" || exit 1
  
  # Create unique repo directory name to avoid conflicts
  local repo_name="homeassistant_$(date +%s)_$"
  local actual_repo_dir="$temp_dir/$repo_name"
  
  # Clean up any existing repository directory first
  if [[ -d "$REPO_DIR" ]]; then
    log "$COLOR_YELLOW" "🧹 Cleaning existing repository directory..."
    rm -rf "$REPO_DIR" || {
      log "$COLOR_RED" "❌ Failed to remove existing repository directory"
      cleanup 1
    }
  fi
  
  # Clone repository with optimizations
  log "$COLOR_BLUE" "📥 Cloning repository..."
  if ! git clone --depth 1 --single-branch --branch main "$GIT_AUTH_REPO" "$actual_repo_dir"; then
    # Try different branch names if main fails
    log "$COLOR_YELLOW" "⚠️ Failed to clone 'main' branch, trying 'master'..."
    if ! git clone --depth 1 --single-branch --branch master "$GIT_AUTH_REPO" "$actual_repo_dir"; then
      # Try default branch
      log "$COLOR_YELLOW" "⚠️ Failed to clone 'master' branch, trying default branch..."
      if ! git clone --depth 1 "$GIT_AUTH_REPO" "$actual_repo_dir"; then
        log "$COLOR_RED" "❌ Git clone failed on all attempts"
        notify "Updater Error" "Git clone failed - tried main, master, and default branches" 5
        cleanup 1
      fi
    fi
  fi
  
  # Update REPO_DIR to point to the actual cloned directory
  REPO_DIR="$actual_repo_dir"

  # Export functions for parallel processing
  export -f update_addon get_latest_tag safe_jq log get_ghcr_token update_config_files update_changelog
  export -f get_dockerhub_tags
  export CONFIG_PATH CACHE_DIR COLOR_RESET COLOR_GREEN COLOR_BLUE COLOR_DARK_BLUE
  export COLOR_YELLOW COLOR_RED COLOR_PURPLE COLOR_CYAN LOG_FILE DRY_RUN DEBUG

  # Process addons in parallel
  process_addons_parallel "$REPO_DIR"

  # Commit and push changes
  if [[ ${#UPDATED_ADDONS[@]} -gt 0 || ${#UNCHANGED_ADDONS[@]} -gt 0 ]]; then
    commit_and_push "$REPO_DIR"
  fi

  # Generate and display summary
  local summary
  summary=$(generate_summary)
  
  local end_time
  end_time=$(date +%s)
  local duration=$((end_time - start_time))
  
  summary+="
⏱️ Execution time: ${duration}s"

  echo "$summary"
  notify "Add-on Updater" "$summary" 3
  
  log "$COLOR_BLUE" "🎉 Update process completed successfully in ${duration}s"
  
  # Cleanup
  cd / && rm -rf "$temp_dir" 2>/dev/null || true
}

# Run main function with all arguments
main "$@"
