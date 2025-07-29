#!/usr/bin/env bash
set -eo pipefail

# Configuration
CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"
MAX_LOG_FILES=5
MAX_LOG_LINES=50

# Color definitions
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_DARK_BLUE="\033[0;94m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
COLOR_CYAN="\033[0;36m"

# Initialize notification settings
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

# Improved lock handling with flock
acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
        log_with_timestamp "$COLOR_RED" "⚠️ Another update process (PID $pid) is running. Exiting."
        exit 1
    fi
    echo $$ >&9
}

release_lock() {
    flock -u 9
    exec 9>&-
    rm -f "$LOCK_FILE"
}

# Logging functions
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

# Log rotation
rotate_logs() {
    if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_LINES" ]; then
        log "$COLOR_YELLOW" "📜 Rotating log file..."
        
        for ((i=MAX_LOG_FILES-1; i>=1; i--)); do
            [ -f "${LOG_FILE}.${i}" ] && mv "${LOG_FILE}.${i}" "${LOG_FILE}.$((i+1))"
        done
        
        tail -n "$MAX_LOG_LINES" "$LOG_FILE" > "${LOG_FILE}.1" 2>/dev/null || true
        : > "$LOG_FILE"
    fi
}

# Load configuration
load_config() {
    [ ! -f "$CONFIG_PATH" ] && {
        log_with_timestamp "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
        exit 1
    }

    GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
    GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
    GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
    CHECK_CRON=$(jq -r '.check_cron // "0 4 * * *"' "$CONFIG_PATH")
    TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
    MAX_LOG_LINES=$(jq -r '.max_log_lines // 50' "$CONFIG_PATH")
    DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
    SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")
    DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")

    # Notification configuration
    NOTIFICATION_SETTINGS[enabled]=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        NOTIFICATION_SETTINGS[service]=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[url]=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[token]=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[to]=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_success]=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_error]=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
        NOTIFICATION_SETTINGS[on_updates]=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")
    fi

    export TZ="$TIMEZONE"
    
    # Construct authenticated repo URL
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
        GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#(https?://)#\1$GITHUB_USERNAME:$GITHUB_TOKEN@#")
    else
        GIT_AUTH_REPO="$GITHUB_REPO"
    fi
}

# Repository management
clone_or_update_repo() {
    log "$COLOR_PURPLE" "🔮 Checking GitHub repository for updates..."
    
    if [ ! -d "$REPO_DIR" ]; then
        log "$COLOR_CYAN" "📦 Cloning repository from $GITHUB_REPO..."
        
        [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_TOKEN" ] && {
            log "$COLOR_RED" "❌ GitHub credentials not configured!"
            log "$COLOR_YELLOW" "   Please set github_username and github_token"
            exit 1
        }
        
        if git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"; then
            log "$COLOR_GREEN" "✅ Successfully cloned repository"
        else
            log "$COLOR_RED" "❌ Failed to clone repository"
            exit 1
        fi
    else
        cd "$REPO_DIR" || {
            log "$COLOR_RED" "❌ Failed to enter repository directory"
            exit 1
        }
        
        log "$COLOR_CYAN" "🔄 Pulling latest changes from GitHub..."
        
        git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
            log "$COLOR_RED" "❌ $REPO_DIR is not a git repository!"
            exit 1
        }
        
        # Clean up any local changes
        git reset --hard HEAD >> "$LOG_FILE" 2>&1
        git clean -fd >> "$LOG_FILE" 2>&1
        
        if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
            log "$COLOR_GREEN" "✅ Successfully pulled latest changes"
        else
            log "$COLOR_RED" "❌ Failed to pull changes"
            exit 1
        fi
    fi
}

# Docker image version checking
get_latest_docker_tag() {
    local image="$1"
    local image_name=$(echo "$image" | cut -d: -f1)
    local version="latest"
    
    # Skip version check for non-repository images
    [[ "$image_name" != *"/"* ]] && {
        echo "$version"
        return
    }

    local namespace=$(echo "$image_name" | cut -d/ -f1)
    local repo=$(echo "$image_name" | cut -d/ -f2)
    local api_url
    
    if [ "$namespace" = "$repo" ]; then
        api_url="https://registry.hub.docker.com/v2/repositories/library/$repo/tags/"
    else
        api_url="https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags/"
    fi
    
    version=$(curl -sSf --connect-timeout 10 "$api_url" | \
        jq -r '.results[] | select(.name != "latest" and (.name | test("^[vV]?[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))) | .name' 2>/dev/null | \
        sort -Vr | head -n1) || true

    [[ -z "$version" ]] && version="latest"
    echo "$version"
}

# Add-on update functions with s6 resilience
update_addon_if_needed() {
    local addon_path="$1"
    local addon_name=$(basename "$addon_path")
    
    [ "$addon_name" = "updater" ] && {
        log "$COLOR_BLUE" "🔧 Skipping updater addon (self)"
        return
    }

    (
        # Run in subshell to isolate from s6 signals
        log "$COLOR_CYAN" "🔍 Checking add-on: ${COLOR_DARK_BLUE}$addon_name${COLOR_CYAN}"

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
            log "$COLOR_YELLOW" "⚠️ No Docker image found for ${COLOR_DARK_BLUE}$addon_name"
            image="$addon_name:latest"
        }

        local latest_version=$(get_latest_docker_tag "$image")

        log "$COLOR_BLUE" "   Current version: $current_version"
        log "$COLOR_BLUE" "   Docker image: $image"
        log "$COLOR_BLUE" "   Available version: $latest_version"

        if [ "$latest_version" != "$current_version" ]; then
            handle_addon_update "$addon_path" "$addon_name" "$current_version" "$latest_version" "$image"
        else
            log "$COLOR_GREEN" "✔️ ${COLOR_DARK_BLUE}$addon_name${COLOR_GREEN} already up to date"
        fi
    ) || {
        log "$COLOR_YELLOW" "⚠️ Addon check interrupted for ${COLOR_DARK_BLUE}$addon_name"
    }
}

handle_addon_update() {
    local addon_path="$1" addon_name="$2" current_version="$3" latest_version="$4" image="$5"
    
    log "$COLOR_GREEN" "⬆️ Update available for ${COLOR_DARK_BLUE}$addon_name${COLOR_GREEN}: $current_version → $latest_version"
    
    [ "$DRY_RUN" = "true" ] && {
        log "$COLOR_CYAN" "🛑 Dry run enabled - would update ${COLOR_DARK_BLUE}$addon_name${COLOR_CYAN} to $latest_version"
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
    
    [ "${NOTIFICATION_SETTINGS[on_updates]}" = "true" ] &&
        send_notification "Add-on Update Available" \
            "Update for $addon_name: $current_version → $latest_version\nImage: $image" \
            3
}

update_config_file() {
    local config_file="$1" version="$2" addon_name="$3" file_type="$4"
    
    if jq --arg v "$version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null; then
        if jq -e . "$config_file.tmp" >/dev/null 2>&1; then
            mv "$config_file.tmp" "$config_file"
            log "$COLOR_GREEN" "✅ Updated version in $file_type for ${COLOR_DARK_BLUE}$addon_name"
        else
            log "$COLOR_RED" "❌ Generated invalid JSON for $file_type in ${COLOR_DARK_BLUE}$addon_name"
            rm -f "$config_file.tmp"
        fi
    else
        log "$COLOR_RED" "❌ Failed to update $file_type for ${COLOR_DARK_BLUE}$addon_name"
    fi
}

update_changelog() {
    local addon_path="$1" slug="$2" current_version="$3" latest_version="$4" image="$5"
    
    local changelog_file="$addon_path/CHANGELOG.md"
    local source_url="https://hub.docker.com/r/$(echo "$image" | cut -d: -f1)"
    local update_time=$(date '+%Y-%m-%d %H:%M:%S')

    [ ! -f "$changelog_file" ] && {
        printf "# CHANGELOG for %s\n\n## Initial version: %s\nDocker Image: [%s](%s)\n\n" \
            "$slug" "$current_version" "$image" "$source_url" > "$changelog_file"
        log "$COLOR_BLUE" "   Created new CHANGELOG.md for ${COLOR_DARK_BLUE}$slug"
    }

    local new_entry="## $latest_version ($update_time)\n- Update from $current_version to $latest_version\n- Docker Image: [$image]($source_url)\n\n"
    printf "%b$(cat "$changelog_file")" "$new_entry" > "$changelog_file.tmp" && 
        mv "$changelog_file.tmp" "$changelog_file" &&
        log "$COLOR_GREEN" "✅ Updated CHANGELOG.md for ${COLOR_DARK_BLUE}$slug"
}

# Git operations
commit_and_push_changes() {
    cd "$REPO_DIR" || return 1

    # Check for changes
    if [ -n "$(git status --porcelain)" ]; then
        git add .
        
        if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
            log "$COLOR_GREEN" "✅ Changes committed"
            
            [ "$SKIP_PUSH" = "true" ] && {
                log "$COLOR_CYAN" "⏸️ Skip push enabled - changes not pushed"
                return 0
            }

            if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
                log "$COLOR_GREEN" "✅ Git push successful"
                [ "${NOTIFICATION_SETTINGS[on_success]}" = "true" ] &&
                    send_notification "Add-on Updater Success" \
                        "Successfully updated add-ons and pushed changes" \
                        0
            else
                log "$COLOR_RED" "❌ Git push failed"
                [ "${NOTIFICATION_SETTINGS[on_error]}" = "true" ] &&
                    send_notification "Add-on Updater Error" \
                        "Failed to push changes to repository" \
                        5
                return 1
            fi
        else
            log "$COLOR_RED" "❌ Failed to commit changes"
            return 1
        fi
    else
        log "$COLOR_BLUE" "📦 No add-on updates found"
    fi
    
    return 0
}

# Notification function
send_notification() {
    [ "${NOTIFICATION_SETTINGS[enabled]}" = "false" ] && return

    local title="$1"
    local message="$2"
    local priority="${3:-0}"
    
    case "${NOTIFICATION_SETTINGS[service]}" in
        "gotify")
            [ -z "${NOTIFICATION_SETTINGS[url]}" ] || [ -z "${NOTIFICATION_SETTINGS[token]}" ] && {
                log "$COLOR_RED" "❌ Gotify configuration incomplete"
                return
            }
            curl -sSf -X POST \
                -H "Content-Type: application/json" \
                -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":$priority}" \
                "${NOTIFICATION_SETTINGS[url]}/message?token=${NOTIFICATION_SETTINGS[token]}" >> "$LOG_FILE" 2>&1 || \
                log "$COLOR_RED" "❌ Failed to send Gotify notification"
            ;;
        *)
            log "$COLOR_YELLOW" "⚠️ Notification service ${NOTIFICATION_SETTINGS[service]} not implemented"
            ;;
    esac
}

# Check if current time matches cron schedule
should_run_from_cron() {
    local cron_schedule="$1"
    [ -z "$cron_schedule" ] && return 1

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

# Main update function
perform_update_check() {
    local start_time=$(date +%s)
    log_with_timestamp "$COLOR_PURPLE" "🚀 Starting update check"
    
    clone_or_update_repo

    cd "$REPO_DIR" || return 1
    git config user.email "updater@local"
    git config user.name "HomeAssistant Updater"

    # Check all add-ons
    for addon_path in "$REPO_DIR"/*/; do
        [ -d "$addon_path" ] && update_addon_if_needed "$addon_path"
    done

    # Commit and push changes if any
    commit_and_push_changes
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    log_with_timestamp "$COLOR_PURPLE" "🏁 Update check completed in ${duration} seconds"
}

# Main execution
main() {
    # Clear log file on startup and rotate if needed
    rotate_logs
    : > "$LOG_FILE"
    
    # Check for lock and load configuration
    acquire_lock
    load_config
    
    # Initial logging
    log_with_timestamp "$COLOR_PURPLE" "🔮 Starting Home Assistant Add-on Updater"
    log_configuration
    
    # First run on startup
    perform_update_check

    # Main loop - only run when cron schedule matches
    log "$COLOR_GREEN" "⏳ Waiting for next scheduled run ($CHECK_CRON)..."
    while true; do
        if should_run_from_cron "$CHECK_CRON"; then
            perform_update_check
            # Sleep for 61 minutes to prevent multiple runs in same minute
            sleep 3660
        else
            sleep 60
        fi
    done
}

log_configuration() {
    log "$COLOR_GREEN" "⚙️ Configuration:"
    log "$COLOR_GREEN" "   - GitHub Repo: $GITHUB_REPO"
    log "$COLOR_GREEN" "   - Dry run: $DRY_RUN"
    log "$COLOR_GREEN" "   - Skip push: $SKIP_PUSH"
    log "$COLOR_GREEN" "   - Check cron: $CHECK_CRON"
    log "$COLOR_GREEN" "   - Timezone: $TIMEZONE"
    log "$COLOR_GREEN" "   - Max log lines: $MAX_LOG_LINES"
    
    if [ "${NOTIFICATION_SETTINGS[enabled]}" = "true" ]; then
        log "$COLOR_GREEN" "🔔 Notifications: Enabled (Service: ${NOTIFICATION_SETTINGS[service]})"
    else
        log "$COLOR_GREEN" "🔔 Notifications: Disabled"
    fi
}

# Run main function
main
