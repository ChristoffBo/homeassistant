#!/usr/bin/env bash
set -eo pipefail

# ========= CONFIG =========
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

# Load config values from options.json
github_repo=$(jq -r '.github_repo // ""' "$CONFIG_PATH")
gitea_repo=$(jq -r '.gitea_repo // ""' "$CONFIG_PATH")
github_username=$(jq -r '.github_username // ""' "$CONFIG_PATH")
github_token=$(jq -r '.github_token // ""' "$CONFIG_PATH")
gitea_token=$(jq -r '.gitea_token // ""' "$CONFIG_PATH")
timezone=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
dry_run=$(jq -r '.dry_run // false' "$CONFIG_PATH")
skip_push=$(jq -r '.skip_push // false' "$CONFIG_PATH")
debug=$(jq -r '.debug // false' "$CONFIG_PATH")
notifications_enabled=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
notification_service=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
notification_url=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
notification_token=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
notification_to=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
notify_on_success=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
notify_on_error=$(jq -r '.notify_on_error // false' "$CONFIG_PATH")
notify_on_updates=$(jq -r '.notify_on_updates // false' "$CONFIG_PATH")

# Color output for logs
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[1;33m"
COLOR_RED="\033[0;31m"
COLOR_CYAN="\033[0;36m"

log() {
    local level="$1"
    local msg="$2"
    local color="$3"
    local timestamp
    timestamp=$(TZ="$timezone" date "+%Y-%m-%d %H:%M:%S %Z")
    echo -e "${color}[${timestamp}] ${level} ${msg}${COLOR_RESET}" | tee -a "$LOG_FILE"
}

info() { log "ℹ️" "$1" "$COLOR_CYAN"; }
success() { log "✅" "$1" "$COLOR_GREEN"; }
warning() { log "⚠️" "$1" "$COLOR_YELLOW"; }
error() { log "❌" "$1" "$COLOR_RED"; }

debug_log() {
    if [ "$debug" = true ]; then
        info "🐛 $1"
    fi
}

# Send notification via Gotify (expand for other services if needed)
send_notification() {
    local title="$1"
    local message="$2"
    if [ "$notifications_enabled" != true ]; then
        debug_log "Notifications disabled, skipping sending notification."
        return
    fi

    if [ "$notification_service" = "gotify" ]; then
        debug_log "Sending Gotify notification to $notification_url"
        local payload
        payload=$(jq -n --arg title "$title" --arg message "$message" --arg priority "0" \
            '{title: $title, message: $message, priority: ($priority | tonumber)}')

        curl -s -X POST \
            -H "Content-Type: application/json" \
            -H "X-Gotify-Key: $notification_token" \
            -d "$payload" \
            "$notification_url/message" >/dev/null 2>&1

        success "Gotify notification sent"
    else
        warning "Notification service $notification_service not implemented"
    fi
}

# Git clone or pull repo (GitHub or Gitea)
git_update_repo() {
    local repo_url="$1"
    local repo_token="$2"
    local repo_dir="$3"
    local repo_username="$4"

    export HOME=/tmp
    mkdir -p "$HOME"

    if [ ! -d "$repo_dir/.git" ]; then
        info "Cloning repository $repo_url"
        git clone --depth=1 "$repo_url" "$repo_dir"
    else
        info "Repository exists. Pulling latest changes..."
        cd "$repo_dir"
        git fetch --all --tags
        git reset --hard "origin/main"
    fi
}

# Fetch latest docker tag version (filter out latest, date tags, arch prefixes)
fetch_latest_version() {
    local image="$1"  # e.g. "2fauth/2fauth" or "ghcr.io/alexbelgium/gitea"
    local registry=""
    local repo=""
    local tags_json
    local tags
    local filtered_tags=()
    local latest_version=""

    if echo "$image" | grep -q "/"; then
        if echo "$image" | grep -qE "^ghcr.io/"; then
            registry="ghcr.io"
            repo="${image#ghcr.io/}"
        elif echo "$image" | grep -qE "^lscr.io/"; then
            registry="lscr.io"
            repo="${image#lscr.io/}"
        else
            registry="docker.io"
            repo="$image"
        fi
    else
        registry="docker.io"
        repo="$image"
    fi

    # Normalize docker.io repo
    if [ "$registry" = "docker.io" ] && ! echo "$repo" | grep -q "/"; then
        repo="library/$repo"
    fi

    debug_log "Fetching tags for $registry/$repo"

    case "$registry" in
        docker.io)
            tags_json=$(curl -s "https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100")
            ;;
        ghcr.io)
            if [ -n "$github_token" ]; then
                tags_json=$(curl -s -H "Authorization: Bearer $github_token" "https://ghcr.io/v2/$repo/tags/list")
            else
                tags_json=$(curl -s "https://ghcr.io/v2/$repo/tags/list")
            fi
            ;;
        lscr.io)
            tags_json=$(curl -s "https://lscr.io/v2/$repo/tags/list")
            ;;
        *)
            error "Unsupported registry: $registry"
            return 1
            ;;
    esac

    if [ -z "$tags_json" ]; then
        error "Failed to fetch tags for $image"
        echo "latest"
        return 1
    fi

    # Parse tags
    if [ "$registry" = "docker.io" ]; then
        tags=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null || echo "")
    else
        tags=$(echo "$tags_json" | jq -r '.tags[]' 2>/dev/null || echo "")
    fi

    for tag in $tags; do
        # Filter tags
        if [ "$tag" = "latest" ] || [ -z "$tag" ]; then
            continue
        fi
        if echo "$tag" | grep -Eq '^[0-9]{4}[-_.]?[0-9]{2}[-_.]?[0-9]{2}'; then
            continue
        fi
        if echo "$tag" | grep -Eq '^(amd64|armhf|armv7|arm64|i386)-'; then
            continue
        fi
        if echo "$tag" | grep -Eq '^v?[0-9]+\.[0-9]+\.[0-9]+'; then
            filtered_tags+=("$tag")
        fi
    done

    if [ ${#filtered_tags[@]} -eq 0 ]; then
        warning "No valid semantic version tags found for $image, defaulting to 'latest'"
        latest_version="latest"
    else
        latest_version=$(printf '%s\n' "${filtered_tags[@]}" | sed 's/^v//' | sort -rV | head -n1)
    fi

    echo "$latest_version"
}

# Compare semantic versions, returns 0 if $1 >= $2 else 1
version_gte() {
    # Using sort -V for comparison
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -rV | head -n1)" = "$1" ]
}

main() {
    info "🔁 Home Assistant Add-on Updater Starting"

    if [ -z "$github_repo" ] && [ -z "$gitea_repo" ]; then
        error "No GitHub or Gitea repository URL configured"
        exit 1
    fi

    # Determine repo to use: GitHub preferred if set, else Gitea
    if [ -n "$github_repo" ]; then
        repo_url="$github_repo"
        repo_token="$github_token"
        info "Using GitHub repository and credentials"
    elif [ -n "$gitea_repo" ]; then
        repo_url="$gitea_repo"
        repo_token="$gitea_token"
        info "Using Gitea repository and credentials"
    fi

    # Clone or pull repo
    git_update_repo "$repo_url" "$repo_token" "$REPO_DIR" "$github_username"

    info "Git pull completed."

    # For report summary
    local summary=""

    # Read addons list (assumes addons are subdirs in repo)
    addons=$(find "$REPO_DIR/addons" -mindepth 1 -maxdepth 1 -type d -exec basename {} \;)

    for addon in $addons; do
        addon_dir="$REPO_DIR/addons/$addon"
        config_json="$addon_dir/config.json"

        if [ ! -f "$config_json" ]; then
            warning "Skipping $addon: config.json missing"
            continue
        fi

        # Read docker image and current version from config.json
        docker_image=$(jq -r '.image // empty' "$config_json")
        current_version=$(jq -r '.version // empty' "$config_json")

        if [ -z "$docker_image" ]; then
            warning "Skipping $addon: no docker image specified"
            continue
        fi

        info "Checking add-on: $addon"
        debug_log "Current version: $current_version"
        debug_log "Docker image: $docker_image"

        available_version=$(fetch_latest_version "$docker_image")

        if [ "$available_version" = "latest" ]; then
            warning "Could not determine a valid latest version for $addon; skipping update"
            summary+="\n$addon: No valid version found, using 'latest'"
            continue
        fi

        info "Add-on $addon available version: $available_version"

        if [ -z "$current_version" ] || ! version_gte "$current_version" "$available_version" ; then
            info "Add-on $addon update available: $current_version -> $available_version"
            if [ "$dry_run" = true ]; then
                info "Dry run enabled, not updating $addon"
                summary+="\n$addon: Update available ($current_version -> $available_version), dry run, no change"
            else
                # Update config.json version
                jq --arg ver "$available_version" '.version = $ver' "$config_json" > "$config_json.tmp" && mv "$config_json.tmp" "$config_json"

                # Commit changes unless skip_push
                if [ "$skip_push" = false ]; then
                    cd "$REPO_DIR"
                    git config user.name "Home Assistant Updater"
                    git config user.email "updater@local"
                    git add "$config_json"
                    git commit -m "Update $addon version to $available_version"
                    git push origin main
                else
                    info "Skip push enabled, not pushing commit"
                fi

                summary+="\n$addon: Updated from $current_version to $available_version"
                success "Updated $addon to version $available_version"
            fi
        else
            info "Add-on $addon already up to date ($current_version)"
            summary+="\n$addon: Already up to date ($current_version)"
        fi
    done

    # Send notification summary always
    if [ "$notifications_enabled" = true ]; then
        send_notification "Add-on Update Summary" "Add-on Update Summary${summary}"
    fi

    success "Add-on update check complete."
}

main "$@"
