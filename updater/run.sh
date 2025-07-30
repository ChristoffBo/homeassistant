#!/usr/bin/with-contenv bashio
#!/usr/bin/env bash
# shellcheck shell=bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/$(jq -r '.repository' "$CONFIG_PATH" | cut -d/ -f2)"
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
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

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
DRY_RUN=false
VERBOSE=false

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
    [ "$VERBOSE" = "true" ] && log_with_timestamp "$COLOR_PURPLE" "🐛 $*"
}

# ======================
# INITIALIZATION
# ======================
initialize() {
    bashio::log.info "Starting $(lastversion --version)"
    
    if bashio::config.true "dry_run"; then
        DRY_RUN=true
        log_warning "Dry run mode enabled - no changes will be made"
    fi
    
    VERBOSE=$(bashio::config 'verbose')
    GITUSER=$(bashio::config 'gituser')
    GITMAIL=$(bashio::config 'gitmail')
    
    git config --system http.sslVerify false
    git config --system credential.helper 'cache --timeout 7200'
    git config --system user.name "${GITUSER}"
    [[ "$GITMAIL" != "null" ]] && git config --system user.email "${GITMAIL}"
    
    if bashio::config.has_value 'gitapi'; then
        GITHUB_API_TOKEN=$(bashio::config 'gitapi')
        export GITHUB_API_TOKEN
    fi
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

    GITHUB_REPO=$(jq -r '.repository // empty' "$CONFIG_PATH")
    GITHUB_USERNAME=$(jq -r '.gituser // empty' "$CONFIG_PATH")
    GITHUB_TOKEN=$(jq -r '.gitapi // empty' "$CONFIG_PATH")
    TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
    DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
    DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
    VERBOSE=$(jq -r '.verbose // false' "$CONFIG_PATH")

    export TZ="$TIMEZONE"

    # Construct authenticated repo URL
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
        GIT_AUTH_REPO="https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/${GITHUB_REPO}"
    else
        GIT_AUTH_REPO="https://github.com/${GITHUB_REPO}"
    fi

    log_configuration
}

log_configuration() {
    log_info "========== CONFIGURATION =========="
    log_info "GitHub Repo: $GITHUB_REPO"
    log_info "Dry Run: $DRY_RUN"
    log_info "Timezone: $TIMEZONE"
    log_info "Verbose Mode: $VERBOSE"
    log_info "=================================="
}

# ======================
# REPOSITORY MANAGEMENT
# ======================
clone_or_update_repo() {
    log_info "Checking GitHub repository for updates..."
    
    if [ ! -d "$REPO_DIR" ]; then
        log_info "Cloning repository from $GITHUB_REPO..."
        
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
        send_notification "Add-on Updater Error" "Failed to pull repository $GITHUB_REPO after recovery attempts" 5
        return 1
    fi
}

# ======================
# VERSION CHECKING
# ======================
get_latest_version() {
    local addon_path="$1"
    local config_file="$addon_path/updater.json"
    
    if [ ! -f "$config_file" ]; then
        log_warning "No updater.json found for $(basename "$addon_path")"
        return 1
    fi

    local UPSTREAM=$(jq -r '.upstream_repo // empty' "$config_file")
    local BETA=$(jq -r '.github_beta // false' "$config_file")
    local FULLTAG=$(jq -r '.github_fulltag // false' "$config_file")
    local HAVINGASSET=$(jq -r '.github_havingasset // false' "$config_file")
    local SOURCE=$(jq -r '.source // "github"' "$config_file")
    local FILTER_TEXT=$(jq -r '.github_tagfilter // empty' "$config_file")
    local EXCLUDE_TEXT=$(jq -r '.github_exclude // "zzzzzzzzzzzzzzzz"' "$config_file")
    local BYDATE=$(jq -r '.dockerhub_by_date // false' "$config_file")
    local LISTSIZE=$(jq -r '.dockerhub_list_size // 100' "$config_file")

    if [ "$SOURCE" = "dockerhub" ]; then
        get_dockerhub_version "$UPSTREAM" "$FILTER_TEXT" "$EXCLUDE_TEXT" "$BETA" "$BYDATE" "$LISTSIZE"
    else
        get_github_version "$UPSTREAM" "$BETA" "$FULLTAG" "$HAVINGASSET" "$FILTER_TEXT" "$EXCLUDE_TEXT"
    fi
}

get_dockerhub_version() {
    local UPSTREAM="$1"
    local FILTER_TEXT="$2"
    local EXCLUDE_TEXT="$3"
    local BETA="$4"
    local BYDATE="$5"
    local LISTSIZE="$6"
    
    local DOCKERHUB_REPO="${UPSTREAM%%/*}"
    local DOCKERHUB_IMAGE=$(echo "$UPSTREAM" | cut -d "/" -f2)
    
    local API_URL="https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags"
    local FILTER="page_size=$LISTSIZE"
    
    [ -n "$FILTER_TEXT" ] && FILTER="${FILTER}&name=$FILTER_TEXT"
    [ "$BYDATE" = "true" ] && FILTER="${FILTER}&ordering=last_updated"
    
    local response=$(curl -sSf --connect-timeout 10 "${API_URL}?${FILTER}" || echo "")
    
    if [ -z "$response" ]; then
        log_error "Failed to fetch Docker Hub tags"
        return 1
    fi
    
    local version=$(echo "$response" | jq -r '.results[] | .name' | \
        grep -v -E 'latest|dev|nightly|beta' | \
        grep -v "$EXCLUDE_TEXT" | \
        sort -V | \
        tail -n 1)
    
    if [ "$BETA" = "true" ]; then
        local beta_version=$(echo "$response" | jq -r '.results[] | .name' | \
            grep -v 'latest' | \
            grep -E 'dev|nightly|beta' | \
            grep -v "$EXCLUDE_TEXT" | \
            sort -V | \
            tail -n 1)
        [ -n "$beta_version" ] && version="$beta_version"
    fi
    
    if [ "$BYDATE" = "true" ] && [ -n "$version" ]; then
        local last_updated=$(echo "$response" | jq -r --arg v "$version" '.results[] | select(.name==$v) | .last_updated')
        last_updated="${last_updated%T*}"
        version="${version}-${last_updated}"
    fi
    
    echo "$version"
}

get_github_version() {
    local UPSTREAM="$1"
    local BETA="$2"
    local FULLTAG="$3"
    local HAVINGASSET="$4"
    local FILTER_TEXT="$5"
    local EXCLUDE_TEXT="$6"
    
    local ARGUMENTS=""
    [ "$BETA" = "true" ] && ARGUMENTS="$ARGUMENTS --pre"
    [ "$FULLTAG" = "true" ] && ARGUMENTS="$ARGUMENTS --format tag"
    [ "$HAVINGASSET" = "true" ] && ARGUMENTS="$ARGUMENTS --having-asset"
    [ -n "$FILTER_TEXT" ] && ARGUMENTS="$ARGUMENTS --only $FILTER_TEXT"
    [ -n "$EXCLUDE_TEXT" ] && ARGUMENTS="$ARGUMENTS --exclude $EXCLUDE_TEXT"
    
    local version=$(lastversion "$UPSTREAM" $ARGUMENTS 2>/dev/null || echo "")
    
    if [ -z "$version" ]; then
        # Fallback to checking packages if no release found
        version=$(check_github_packages "$UPSTREAM")
    fi
    
    echo "$version"
}

check_github_packages() {
    local UPSTREAM="$1"
    local packages=$(curl -s -L "https://github.com/${UPSTREAM}/packages" | \
        sed -n "s/.*\/container\/package\/\([^\"]*\).*/\1/p" | head -n 1)
    
    [ -n "$packages" ] && \
        curl -s -L "https://github.com/${UPSTREAM}/pkgs/container/${packages}" | \
        sed -n "s/.*?tag=\([^\"]*\)\">.*/\1/p" | \
        grep -v -E 'latest|dev|nightly|beta' | \
        sort -V | \
        tail -n 1
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

    if [ ! -f "$addon_path/updater.json" ]; then
        log_info "Skipping $addon_name (no updater.json)"
        return
    }

    local PAUSED=$(jq -r '.paused // false' "$addon_path/updater.json")
    [ "$PAUSED" = "true" ] && {
        log_info "Skipping $addon_name (paused)"
        return
    }

    log_info "Checking add-on: $addon_name"
    
    local current_version=$(jq -r '.upstream_version' "$addon_path/updater.json")
    local latest_version=$(get_latest_version "$addon_path")
    
    if [ -z "$latest_version" ]; then
        log_warning "Could not determine latest version for $addon_name"
        UNCHANGED_ADDONS["$addon_name"]="Version check failed"
        return
    fi

    log_info "Current version: $current_version"
    log_info "Available version: $latest_version"

    if [ "$current_version" != "$latest_version" ]; then
        handle_addon_update "$addon_path" "$addon_name" "$current_version" "$latest_version"
    else
        log_success "$addon_name already up to date"
        UNCHANGED_ADDONS["$addon_name"]="Already up to date"
    fi
}

handle_addon_update() {
    local addon_path="$1" addon_name="$2" current_version="$3" latest_version="$4"
    
    log_success "Update available for $addon_name: $current_version → $latest_version"
    UPDATED_ADDONS["$addon_name"]="$current_version → $latest_version"
    
    [ "$DRY_RUN" = "true" ] && {
        log_info "Dry run enabled - would update $addon_name to $latest_version"
        return
    }

    # Update all relevant files
    for file in "config.json" "config.yaml" "Dockerfile" "build.json" "build.yaml"; do
        if [ -f "$addon_path/$file" ]; then
            sed -i "s/$current_version/$latest_version/g" "$addon_path/$file"
        fi
    done

    # Update version in config files
    if [ -f "$addon_path/config.json" ]; then
        jq --arg v "$latest_version" '.version = $v' "$addon_path/config.json" | sponge "$addon_path/config.json"
    elif [ -f "$addon_path/config.yaml" ]; then
        sed -i "/version:/c\version: \"$latest_version\"" "$addon_path/config.yaml"
    fi

    # Update updater.json
    jq --arg v "$latest_version" '.upstream_version = $v' "$addon_path/updater.json" | sponge "$addon_path/updater.json"
    jq --arg d "$(date '+%Y-%m-%d')" '.last_update = $d' "$addon_path/updater.json" | sponge "$addon_path/updater.json"

    # Update changelog
    update_changelog "$addon_path" "$addon_name" "$current_version" "$latest_version"
}

update_changelog() {
    local addon_path="$1" slug="$2" current_version="$3" latest_version="$4"
    
    local changelog_file="$addon_path/CHANGELOG.md"
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')
    local upstream=$(jq -r '.upstream_repo' "$addon_path/updater.json")
    local source=$(jq -r '.source' "$addon_path/updater.json")

    [ ! -f "$changelog_file" ] && {
        printf "# CHANGELOG for %s\n\n## Initial version: %s\n" "$slug" "$current_version" > "$changelog_file"
    }

    local new_entry="## $latest_version ($update_time)\n- Update from $current_version to $latest_version\n"
    
    if [ "$source" = "github" ]; then
        new_entry+="- Source: [${upstream}](https://github.com/${upstream}/releases)\n\n"
    else
        new_entry+="- Source: ${upstream}\n\n"
    fi
    
    printf "%b$(cat "$changelog_file")" "$new_entry" > "$changelog_file.tmp" && \
        mv "$changelog_file.tmp" "$changelog_file"
}

# ======================
# GIT OPERATIONS
# ======================
commit_and_push_changes() {
    cd "$REPO_DIR" || return 1

    if [ -z "$(git status --porcelain)" ]; then
        log_info "No changes to commit"
        return 0
    fi

    git add .
    
    if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
        log_success "Changes committed"
        
        if [ "$DRY_RUN" = "true" ]; then
            log_info "Dry run - skipping push"
            return 0
        fi

        if git push >> "$LOG_FILE" 2>&1; then
            log_success "Changes pushed successfully"
            return 0
        else
            log_error "Failed to push changes"
            return 1
        fi
    else
        log_error "Failed to commit changes"
        return 1
    fi
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
            curl -sSf -X POST \
                -H "Content-Type: application/json" \
                -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
                "${NOTIFICATION_SETTINGS[url]}message?token=${NOTIFICATION_SETTINGS[token]}" >> "$LOG_FILE" 2>&1 || \
                log_error "Failed to send Gotify notification"
            ;;
        *)
            log_warning "Notification service ${NOTIFICATION_SETTINGS[service]} not implemented"
            ;;
    esac
}

# ======================
# MAIN EXECUTION
# ======================
main() {
    acquire_lock
    initialize
    load_config
    
    log_info "Starting Home Assistant Add-on Updater"
    
    clone_or_update_repo

    cd "$REPO_DIR" || exit 1

    # Process all add-ons
    for addon_path in "$REPO_DIR"/*/; do
        [ -d "$addon_path" ] && update_addon_if_needed "$addon_path"
    done

    # Commit and push changes
    commit_and_push_changes
    
    # Send summary notification
    if [ ${#UPDATED_ADDONS[@]} -gt 0 ]; then
        local summary="Add-on Update Summary\n\n"
        summary+="✅ ${#UPDATED_ADDONS[@]} Add-ons Updated:\n"
        for addon in "${!UPDATED_ADDONS[@]}"; do
            summary+="  - $addon: ${UPDATED_ADDONS[$addon]}\n"
        done
        send_notification "Add-ons Updated" "$summary" 3
    fi

    release_lock
    log_info "Update process completed successfully"
}

main