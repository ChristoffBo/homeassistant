#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
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
        
        # Validate notification settings
        if [ -z "${NOTIFICATION_SETTINGS[service]}" ]; then
            log_error "Notification service is not specified"
            NOTIFICATION_SETTINGS[enabled]=false
        fi
        
        case "${NOTIFICATION_SETTINGS[service]}" in
            "gotify")
                # Enhanced Gotify validation
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
                elif [[ ! "${NOTIFICATION_SETTINGS[token]}" =~ ^[A-Za-z0-9._~+-]+$ ]]; then
                    log_error "Gotify token contains invalid characters"
                    NOTIFICATION_SETTINGS[enabled]=false
                fi
                
                # Test Gotify connection if enabled
                if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
                    if ! curl -sSf --connect-timeout 5 "${NOTIFICATION_SETTINGS[url]}/health" >/dev/null 2>&1; then
                        log_error "Gotify server not reachable at ${NOTIFICATION_SETTINGS[url]}"
                        NOTIFICATION_SETTINGS[enabled]=false
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
        
        # Mask sensitive information in logs
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
        [ "$DEBUG" = "true" ] && log_info "Using cached version for $image_name: $version"
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
        sort -Vr | head -n1
}

get_docker_source_url() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    
    if [[ "$image_name" =~ ^linuxserver/|^lscr.io/linuxserver/ ]]; then
        local lsio_name=$(echo "$image_name" | sed 's|^lscr.io/linuxserver/||;s|^linuxserver/||')
        echo "https://fleet.linuxserver.io/image?name=$lsio_name"
    elif [[ "$image_name" =~ ^ghcr.io/ ]]; then
        local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
        local package=$(echo "$image_name" | cut -d/ -f4)
        echo "https://github.com/$org_repo/pkgs/container/$package"
    else
        local namespace=$(echo "$image_name" | cut -d/ -f1)
        local repo=$(echo "$image_name" | cut -d/ -f2)
        [ "$namespace" = "$repo" ] && 
            echo "https://hub.docker.com/_/$repo" || 
            echo "https://hub.docker.com/r/$namespace/$repo"
    fi
}

# ======================
# ADD-ON PROCESSING
# ======================
update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    
    [ "$addon_name" = "updater" ] && {
        log_info "Skipping updater addon (self)"
        return
    }

    (
        log_info "Checking add-on: $addon_name"

        local image="" current_version="latest"
        local config_file="$addon_path/config.json"
        local build_file="$addon_path/build.json"

        # Try to get image from config.json first
        [ -f "$config_file" ] && {
            image=$(jq -r '.image // empty' "$config_file" 2>/dev/null || true)
            current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null || echo "latest")
        }

        # Fall back to build.json if no image found
        [ -z "$image" ] && [ -f "$build_file" ] && {
            local arch=$(uname -m)
            [ "$arch" = "x86_64" ] && arch="amd64"
            [ -s "$build_file" ] && 
                image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | if type=="string" then . else empty end' "$build_file" 2>/dev/null || true)
        }

        [ -z "$image" ] && {
            log_warning "No Docker image found for $addon_name"
            UNCHANGED_ADDONS["$addon_name"]="No Docker image found"
            return
        }

        local latest_version
        if ! latest_version=$(get_latest_docker_tag "$image"); then
            log_warning "Could not determine latest version for $addon_name"
            UNCHANGED_ADDONS["$addon_name"]="Could not determine latest version"
            return
        fi

        [ -z "$latest_version" ] && latest_version="latest"

        log_info "Current version: $current_version"
        log_info "Docker image: $image"
        log_info "Available version: $latest_version"

        if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
            handle_addon_update "$addon_path" "$addon_name" "$current_version" "$latest_version" "$image"
        else
            log_success "$addon_name already up to date"
            UNCHANGED_ADDONS["$addon_name"]="Already up to date (current: $current_version)"
        fi
    ) || {
        log_warning "Addon check interrupted for $addon_name"
        UNCHANGED_ADDONS["$addon_name"]="Check interrupted"
    }
}

handle_addon_update() {
    local addon_path="$1" addon_name="$2" current_version="$3" latest_version="$4" image="$5"
    
    log_success "Update available for $addon_name: $current_version → $latest_version"
    
    UPDATED_ADDONS["$addon_name"]="$current_version → $latest_version"
    
    [ "$DRY_RUN" = "true" ] && {
        log_info "Dry run enabled - would update $addon_name to $latest_version"
        return
    }

    # Update config.json if it exists
    [ -f "$addon_path/config.json" ] && 
        update_config_file "$addon_path/config.json" "$latest_version" "$addon_name" "config.json"

    # Update build.json if it exists and has a version field
    [ -f "$addon_path/build.json" ] && 
        jq -e '.version' "$addon_path/build.json" >/dev/null 2>&1 && 
        update_config_file "$addon_path/build.json" "$latest_version" "$addon_name" "build.json"

    update_changelog "$addon_path" "$addon_name" "$current_version" "$latest_version" "$image"
}

update_config_file() {
    local config_file="$1" version="$2" addon_name="$3" file_type="$4"
    
    if jq --arg v "$version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null; then
        if jq -e . "$config_file.tmp" >/dev/null 2>&1; then
            mv "$config_file.tmp" "$config_file"
            log_success "Updated version in $file_type for $addon_name"
        else
            log_error "Generated invalid JSON for $file_type in $addon_name"
            rm -f "$config_file.tmp"
        fi
    else
        log_error "Failed to update $file_type for $addon_name"
    fi
}

update_changelog() {
    local addon_path="$1" slug="$2" current_version="$3" latest_version="$4" image="$5"
    
    local changelog_file="$addon_path/CHANGELOG.md"
    local source_url=$(get_docker_source_url "$image")
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')

    [ ! -f "$changelog_file" ] && {
        printf "# CHANGELOG for %s\n\n## Initial version: %s\nDocker Image: [%s](%s)\n\n" \
            "$slug" "$current_version" "$image" "$source_url" > "$changelog_file"
        log_info "Created new CHANGELOG.md for $slug"
    }

    local new_entry="## $latest_version ($update_time)\n- Update from $current_version to $latest_version\n- Docker Image: [$image]($source_url)\n\n"
    printf "%b$(cat "$changelog_file")" "$new_entry" > "$changelog_file.tmp" && 
        mv "$changelog_file.tmp" "$changelog_file" &&
        log_success "Updated CHANGELOG.md for $slug"
}

# ======================
# GIT OPERATIONS
# ======================
commit_and_push_changes() {
    cd "$REPO_DIR" || return 1

    # Check for changes
    if [ -n "$(git status --porcelain)" ]; then
        git add .
        
        if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
            log_success "Changes committed"
            
            [ "$SKIP_PUSH" = "true" ] && {
                log_info "Skip push enabled - changes not pushed"
                return 0
            }

            if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
                log_success "Git push successful"
                return 0
            else
                log_error "Git push failed"
                return 1
            fi
        else
            log_error "Failed to commit changes"
            return 1
        fi
    else
        log_info "No add-on updates found"
    fi
    
    return 0
}

# ======================
# NOTIFICATIONS
# ======================
send_notification() {
    [ "${NOTIFICATION_SETTINGS[enabled]}" = "false" ] && return

    local title="$1"
    local message="$2"
    local priority="${3:-0}"
    
    case "${NOTIFICATION_SETTINGS[service]}" in
        "gotify")
            # Enhanced Gotify validation
            if [[ ! "${NOTIFICATION_SETTINGS[url]}" =~ ^https?:// ]] || [[ -z "${NOTIFICATION_SETTINGS[token]}" ]]; then
                log_error "Invalid Gotify configuration - cannot send notification"
                return
            fi
            
            # Test Gotify connection
            if ! curl -sSf --connect-timeout 5 "${NOTIFICATION_SETTINGS[url]}/health" >/dev/null 2>&1; then
                log_error "Gotify server not reachable at ${NOTIFICATION_SETTINGS[url]}"
                return
            fi
            
            curl -sSf -X POST \
                -H "Content-Type: application/json" \
                -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
                "${NOTIFICATION_SETTINGS[url]}/message?token=${NOTIFICATION_SETTINGS[token]}" >> "$LOG_FILE" 2>&1 || \
                log_error "Failed to send Gotify notification"
            ;;
        "mailrise"|"ntfy")
            curl -sSf -X POST \
                -H "Content-Type: application/json" \
                -d "{\"to\":\"${NOTIFICATION_SETTINGS[to]}\", \"subject\":\"$title\", \"body\":\"$message\"}" \
                "${NOTIFICATION_SETTINGS[url]}" >> "$LOG_FILE" 2>&1 || \
                log_error "Failed to send ${NOTIFICATION_SETTINGS[service]} notification"
            ;;
        "apprise")
            apprise -vv -t "$title" -b "$message" "${NOTIFICATION_SETTINGS[url]}" >> "$LOG_FILE" 2>&1 || \
                log_error "Failed to send Apprise notification"
            ;;
        *)
            log_warning "Unknown notification service: ${NOTIFICATION_SETTINGS[service]}"
            ;;
    esac
}

# ======================
# SUMMARY REPORT
# ======================
generate_summary_report() {
    local message="Add-on Update Summary\n\n"
    
    if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
        message+="✅ ${#UPDATED_ADDONS[@]} Add-ons Updated:\n"
        for addon in "${!UPDATED_ADDONS[@]}"; do
            message+="  - $addon: ${UPDATED_ADDONS[$addon]}\n"
        done
    else
        message+="ℹ️ No add-ons were updated\n"
    fi
    
    message+="\n"
    
    if [ ${#UNCHANGED_ADDONS[@]} -gt 0 ]; then
        message+="ℹ️ ${#UNCHANGED_ADDONS[@]} Add-ons Unchanged:\n"
        for addon in "${!UNCHANGED_ADDONS[@]}"; do
            message+="  - $addon: ${UNCHANGED_ADDONS[$addon]}\n"
        done
    fi
    
    # Add timestamp
    message+="\nLast run: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    
    echo -e "$message"
}

# ======================
# MAIN FUNCTIONS
# ======================
perform_update_check() {
    local start_time=$(date +%s)
    log_info "Starting update check"
    
    clone_or_update_repo

    cd "$REPO_DIR" || return 1
    git config user.email "updater@local"
    git config user.name "HomeAssistant Updater"

    # Initialize tracking arrays
    declare -gA UPDATED_ADDONS=()
    declare -gA UNCHANGED_ADDONS=()

    # Check all add-ons
    for addon_path in "$REPO_DIR"/*/; do
        [ -d "$addon_path" ] && update_addon_if_needed "$addon_path"
    done

    # Commit and push changes if any
    commit_and_push_changes
    
    # Send summary notification
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        local summary=$(generate_summary_report)
        local title="Add-on Update Summary"
        local priority=0
        
        if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
            title="Add-ons Updated (${#UPDATED_ADDONS[@]})"
            priority=3
        fi
        
        send_notification "$title" "$summary" "$priority"
    fi
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    log_info "Update check completed in ${duration} seconds"
}

# ======================
# ENTRY POINT
# ======================
main() {
    acquire_lock
    load_config
    
    log_info "Starting Home Assistant Add-on Updater"
    
    perform_update_check

    release_lock
    
    # Sleep indefinitely after completing the update check
    log_info "Update process completed. Sleeping indefinitely..."
    while true; do
        sleep 3600  # Sleep for 1 hour at a time
    done
}

main