#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/repo"  # Change if your repo clone path differs
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
MAX_LOG_FILES=5
MAX_LOG_LINES=1000

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
# NOTIFICATION SETTINGS
# ======================
declare -A NOTIFICATION_SETTINGS=(
    [enabled]=false
    [service]=""
    [url]=""
    [token]=""
    [to]=""
    [on_success]=false
    [on_error]=true
    [on_updates]=true
)

# ======================
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS

# ======================
# LOGGING FUNCTIONS
# ======================
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

log_error() {
    log_with_timestamp "$COLOR_RED" "❌ $*"
}

log_warning() {
    log_with_timestamp "$COLOR_YELLOW" "⚠️ $*"
}

log_info() {
    log_with_timestamp "$COLOR_BLUE" "ℹ️ $*"
}

log_success() {
    log_with_timestamp "$COLOR_GREEN" "✅ $*"
}

log_debug() {
    [ "$DEBUG" = "true" ] && log_with_timestamp "$COLOR_PURPLE" "🐛 $*"
}

# ======================
# LOCK MANAGEMENT
# ======================
acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
        log_error "Another update process (PID $pid) is running. Exiting."
        exit 1
    fi
    echo $$ >&9
}

release_lock() {
    flock -u 9
    exec 9>&-
    rm -f "$LOCK_FILE"
}

# ======================
# CONFIGURATION LOADING
# ======================
load_config() {
    if [ ! -f "$CONFIG_PATH" ]; then
        log_error "Config file $CONFIG_PATH not found!"
        exit 1
    fi

    # Load basic configuration
    GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
    GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
    GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
    TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
    DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
    SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
    DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")

    # Load notification settings
    NOTIFICATION_SETTINGS[enabled]=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        NOTIFICATION_SETTINGS[service]=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[url]=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[token]=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[to]=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_success]=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_error]=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_updates]=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")
        
        # Ensure URL ends with /
        [[ "${NOTIFICATION_SETTINGS[url]}" != */ ]] && NOTIFICATION_SETTINGS[url]="${NOTIFICATION_SETTINGS[url]}/"
        
        # Validate notification settings
        if [ -z "${NOTIFICATION_SETTINGS[service]}" ]; then
            log_error "Notification service is not specified"
            NOTIFICATION_SETTINGS[enabled]=false
        fi
        
        case "${NOTIFICATION_SETTINGS[service]}" in
            "gotify")
                if [ -z "${NOTIFICATION_SETTINGS[url]}" ]; then
                    log_error "Gotify configuration incomplete - missing URL"
                    NOTIFICATION_SETTINGS[enabled]=false
                elif [[ ! "${NOTIFICATION_SETTINGS[url]}" =~ ^https?:// ]]; then
                    log_error "Gotify URL must start with http:// or https://"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                
                if [ -z "${NOTIFICATION_SETTINGS[token]}" ]; then
                    log_error "Gotify configuration incomplete - missing token"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                
                # Test Gotify connection
                if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
                    log_debug "Testing Gotify connection to ${NOTIFICATION_SETTINGS[url]}health"
                    if ! curl -sSf --connect-timeout 5 "${NOTIFICATION_SETTINGS[url]}health" >/dev/null 2>&1; then
                        log_error "Gotify server not reachable at ${NOTIFICATION_SETTINGS[url]}"
                        NOTIFICATION_SETTINGS[enabled]=false
                    else
                        log_debug "Gotify connection successful"
                    fi
                fi
                ;;
            "mailrise"|"ntfy")
                if [ -z "${NOTIFICATION_SETTINGS[url]}" ] || [ -z "${NOTIFICATION_SETTINGS[to]}" ]; then
                    log_error "${NOTIFICATION_SETTINGS[service]} configuration incomplete - missing URL or recipient"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                ;;
            "apprise")
                if [ -z "${NOTIFICATION_SETTINGS[url]}" ]; then
                    log_error "Apprise configuration incomplete - missing URL"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                if ! command -v apprise >/dev/null; then
                    log_error "Apprise CLI not installed - notifications disabled"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                ;;
            *)
                log_error "Unknown notification service: ${NOTIFICATION_SETTINGS[service]}"
                NOTIFICATION_SETTINGS[enabled]=false
                ;;
        esac
    fi

    export TZ="$TIMEZONE"

    # Construct authenticated repo URL
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
        GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#(https?://)#\1$GITHUB_USERNAME:$GITHUB_TOKEN@#")
    else
        GIT_AUTH_REPO="$GITHUB_REPO"
    fi

    log_configuration
}

log_configuration() {
    log_info "========== CONFIGURATION =========="
    log_info "GitHub Repo: $GITHUB_REPO"
    log_info "Dry Run: $DRY_RUN"
    log_info "Skip Push: $SKIP_PUSH"
    log_info "Timezone: $TIMEZONE"
    log_info "Debug Mode: $DEBUG"
    
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        log_info "Notifications: Enabled (${NOTIFICATION_SETTINGS[service]})"
        log_info "Notify on Success: ${NOTIFICATION_SETTINGS[on_success]}"
        log_info "Notify on Error: ${NOTIFICATION_SETTINGS[on_error]}"
        log_info "Notify on Updates: ${NOTIFICATION_SETTINGS[on_updates]}"
        
        # Mask sensitive info in logs
        if [ "${NOTIFICATION_SETTINGS[service]}" = "gotify" ]; then
            log_info "Gotify URL: ${NOTIFICATION_SETTINGS[url]%%/*}/******"
            log_info "Gotify Token: ****** (hidden)"
        fi
    else
        log_info "Notifications: Disabled"
    fi
    log_info "=================================="
}

# ======================
# REPOSITORY MANAGEMENT
# ======================
clone_or_update_repo() {
    log_info "Checking GitHub repository for updates..."
    
    if [ ! -d "$REPO_DIR" ]; then
        log_info "Cloning repository from $GITHUB_REPO..."
        
        if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_TOKEN" ]; then
            log_error "GitHub credentials not configured!"
            exit 1
        fi
        
        if ! check_github_connectivity; then
            log_error "Cannot connect to GitHub!"
            exit 1
        fi

        if git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"; then
            log_success "Successfully cloned repository"
        else
            log_clone_error
            exit 1
        fi
    else
        cd "$REPO_DIR" || {
            log_error "Failed to enter repository directory"
            exit 1
        }
        
        log_info "Pulling latest changes from GitHub..."
        log_repo_status
        
        if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
            log_error "$REPO_DIR is not a git repository!"
            exit 1
        fi
        
        # Clean up any local changes
        git reset --hard HEAD >> "$LOG_FILE" 2>&1
        git clean -fd >> "$LOG_FILE" 2>&1
        
        if ! git_pull_with_recovery; then
            exit 1
        fi
    fi
}

check_github_connectivity() {
    if ! curl -sSf --connect-timeout 10 https://github.com >/dev/null; then
        log_warning "Please check your internet connection"
        return 1
    fi
    return 0
}

log_clone_error() {
    log_error "Failed to clone repository"
    log_warning "╔════════════════════════════════════════════╗"
    log_warning "║              CLONE ERROR DETAILS            ║"
    log_warning "╠════════════════════════════════════════════╣"
    tail -n 5 "$LOG_FILE" | while read -r line; do
        log_warning "║ $line"
    done
    log_warning "╚════════════════════════════════════════════╝"
}

log_repo_status() {
    log_info "Current HEAD: $(git rev-parse --short HEAD)"
    log_info "Last commit: $(git log -1 --format='%cd %s' --date=format:'%Y-%m-%d %H:%M:%S')"
}

git_pull_with_recovery() {
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log_successful_pull
        return 0
    fi
    
    log_error "Initial git pull failed. Attempting recovery..."
    
    # Handle unfinished rebase/merge if exists
    if [ -d ".git/rebase-merge" ] || [ -d ".git/rebase-apply" ]; then
        log_warning "Detected unfinished rebase, aborting..."
        git rebase --abort >> "$LOG_FILE" 2>&1 || true
    fi
    
    # Try recovery steps
    git fetch origin main >> "$LOG_FILE" 2>&1
    git reset --hard origin/main >> "$LOG_FILE" 2>&1
    
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log_success "Git pull successful after recovery"
        log_info "New HEAD: $(git rev-parse --short HEAD)"
        return 0
    else
        log_error "Git pull still failed after recovery attempts"
        log_error_details
        send_notification "Add-on Updater Error" "Failed to pull repository $GITHUB_REPO after recovery attempts" 5
        return 1
    fi
}

log_successful_pull() {
    log_success "Successfully pulled latest changes"
    log_info "New HEAD: $(git rev-parse --short HEAD)"
    local new_commits=$(git log --pretty=format:'   %h - %s (%cd)' --date=format:'%Y-%m-%d %H:%M:%S' HEAD@{1}..HEAD 2>/dev/null)
    if [ -n "$new_commits" ]; then
        log_info "New commits:"
        echo "$new_commits" | while read -r line; do
            log_info "$line"
        done
    else
        log_info "(No new commits)"
    fi
}

log_error_details() {
    log_warning "╔════════════════════════════════════════════╗"
    log_warning "║               ERROR DETAILS                 ║"
    log_warning "╠════════════════════════════════════════════╣"
    tail -n 10 "$LOG_FILE" | sed 's/^/║ /' | while read -r line; do
        log_warning "$line"
    done
    log_warning "╚════════════════════════════════════════════╝"
}

# ======================
# VERSION CHECKING
# ======================
get_latest_docker_tag() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    local version="latest"
    local cache_file="/tmp/docker_tags_$(echo "$image_name" | tr '/:' '_').cache"
    local cache_age=14400  # 4 hours
    
    # Check cache first
    if [ -f "$cache_file" ] && [ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt $cache_age ]; then
        version=$(cat "$cache_file")
        [ "$DEBUG" = "true" ] && log_debug "Using cached version for $image_name: $version"
        echo "$version"
        return
    fi
    
    # Check different registry types
    if [[ "$image_name" =~ ^linuxserver/|^lscr.io/linuxserver/ ]]; then
        version=$(get_lsio_tag "$image_name")
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
        version=$(get_ghcr_tag "$image_name")
    else
        version=$(get_dockerhub_tag "$image_name")
    fi

    [[ -z "$version" ]] && version="latest"
    echo "$version" > "$cache_file"
    echo "$version"
}

get_lsio_tag() {
    local image_name="$1"
    local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
    
    # Try the new API endpoint first
    local api_response=$(curl -sSf --connect-timeout 10 "https://fleet.linuxserver.io/api/v1/images/$lsio_name/tags" || echo "")
    
    # Fall back to old endpoint if new one fails
    [ -z "$api_response" ] && 
        api_response=$(curl -sSf --connect-timeout 10 "https://api.linuxserver.io/v1/images/$lsio_name/tags" || echo "")
    
    [ -n "$api_response" ] && echo "$api_response" | 
        jq -r '.tags[]? | select(.name != "latest") | .name' 2>/dev/null | 
        grep -E '^[vV]?[0-9]+\.[0-9]+(\.[0-9]+)?$' | 
        sort -Vr | head -n1
}

get_ghcr_tag() {
    local image_name="$1"
    local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
    local package=$(echo "$image_name" | cut -d/ -f4)
    local token=$(curl -sSf --connect-timeout 10 "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token' 2>/dev/null || echo "")
    
    [ -z "$token" ] && return

    curl -sSf --connect-timeout 10 -H "Authorization: Bearer $token" \
        "https://ghcr.io/v2/$org_repo/$package/tags/list" | \
        jq -r '.tags[]? | select(. != "latest" and (. | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?$")))' 2>/dev/null | \
        sort -Vr | head -n1
}

get_dockerhub_tag() {
    local image_name="$1"
    local namespace=$(echo "$image_name" | cut -d/ -f1)
    local repo=$(echo "$image_name" | cut -d/ -f2)
    local api_url
    
    [ "$namespace" = "$repo" ] && 
        api_url="https://registry.hub.docker.com/v2/repositories/library/$repo/tags/" ||
        api_url="https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/"
    
    local api_response=$(curl -sSf --connect-timeout 10 "$api_url" || echo "")
    
    # Return empty if we get a 404
    if [[ "$api_response" == *"404"* ]]; then
        echo ""
        return
    fi
    
    [ -n "$api_response" ] && echo "$api_response" | 
        jq -r '.results[]? | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))) | .name' 2>/dev/null | 
       
