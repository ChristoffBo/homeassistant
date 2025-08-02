#!/usr/bin/env bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
LOCK_FILE="/data/updater.lock"

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

# Read config
read_config() {
    DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
    DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
    TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
    export TZ

    GITHUB_REPO=$(jq -r '.github_repo // empty' "$CONFIG_PATH")
    GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
    GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")

    NOTIFY_ENABLED=$(jq -r '.notifications_enabled // false' "$CONFIG_PATH")
    NOTIFY_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
    NOTIFY_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
    NOTIFY_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
    NOTIFY_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
    NOTIFY_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
    NOTIFY_ERROR=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
    NOTIFY_UPDATES=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")
    SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")

    GIT_AUTH_REPO="$GITHUB_REPO"
    if [[ -n "$GITHUB_USERNAME" && -n "$GITHUB_TOKEN" ]]; then
        GIT_AUTH_REPO="${GITHUB_REPO/https:\/\//https:\/\/$GITHUB_USERNAME:$GITHUB_TOKEN@}"
    fi
}

log() {
    local color="$1"
    shift
    echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

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
        curl -s -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{\"title\":\"$title\",\"message\":\"$message\",\"priority\":$priority}" \
            >> "$LOG_FILE" 2>&1 || log "$COLOR_RED" "❌ Gotify notification failed"
    fi
}

get_latest_tag() {
    local image="$1"
    local image_name="${image%%:*}"
    local cache_file="/tmp/tags_$(echo "$image_name" | tr '/' '_').txt"

    if [[ -f "$cache_file" && $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt 14400 ]]; then
        cat "$cache_file"
        return
    fi

    local tags=""
    if [[ "$image_name" =~ ^ghcr.io/ ]]; then
        local org_repo=$(echo "$image_name" | cut -d/ -f2-3)
        local package=$(echo "$image_name" | cut -d/ -f4)
        local token=$(curl -s "https://ghcr.io/token?scope=repository:$org_repo/$package:pull" | jq -r '.token')
        tags=$(curl -s -H "Authorization: Bearer $token" "https://ghcr.io/v2/$org_repo/$package/tags/list" | jq -r '.tags[]')
    elif [[ "$image_name" =~ ^(linuxserver|lscr.io)/ ]]; then
        local name="${image_name##*/}"
        tags=$(curl -s "https://fleet.linuxserver.io/api/v1/images/$name/tags" | jq -r '.tags[].name')
    else
        local ns_repo="${image_name/library\//}"
        tags=$(curl -s "https://hub.docker.com/v2/repositories/${ns_repo}/tags" | jq -r '.results[].name')
    fi

    echo "$tags" | grep -Ev 'latest|[a-z]' | sort -Vr | head -n1 | tee "$cache_file"
}

update_addon() {
    local addon_path="$1"
    local name=$(basename "$addon_path")

    [[ "$name" == "updater" ]] && return

    log "$COLOR_DARK_BLUE" "🔍 Checking $name"
    local config="$addon_path/config.json"
    local build="$addon_path/build.json"
    local image version latest

    image=$(jq -r '.image // empty' "$config" 2>/dev/null)
    version=$(jq -r '.version // "unknown"' "$config" 2>/dev/null)

    [[ -z "$image" && -f "$build" ]] && {
        image=$(jq -r '.build_from.amd64 // .build_from | strings' "$build" 2>/dev/null)
        version=$(jq -r '.version // "unknown"' "$build" 2>/dev/null)
    }

    [[ -z "$image" ]] && {
        log "$COLOR_YELLOW" "⚠️ No image defined for $name"
        UNCHANGED_ADDONS["$name"]="No image"
        return
    }

    latest=$(get_latest_tag "$image")
    [[ -z "$latest" ]] && {
        log "$COLOR_YELLOW" "⚠️ No valid version tag found for $image"
        UNCHANGED_ADDONS["$name"]="No valid tag"
        return
    }

    if [[ "$version" != "$latest" ]]; then
        log "$COLOR_GREEN" "⬆️ $name updated from $version to $latest"
        UPDATED_ADDONS["$name"]="$version → $latest"

        if [[ "$DRY_RUN" == "true" ]]; then
            log "$COLOR_PURPLE" "💡 Dry run active: skipping update of $name"
            return
        fi

        jq --arg v "$latest" '.version = $v' "$config" > "$config.tmp" && mv "$config.tmp" "$config"
        if [[ -f "$build" && $(jq -e '.version' "$build") ]]; then
            jq --arg v "$latest" '.version = $v' "$build" > "$build.tmp" && mv "$build.tmp" "$build"
        fi

        local changelog="$addon_path/CHANGELOG.md"
        local link=$(echo "$image" | sed 's|^ghcr.io|https://github.com|' | sed 's|/|/pkgs/container/|' | sed 's|$|/tags|')
        printf "## %s\n- Updated from %s to %s\n- Docker: [%s](%s)\n\n" "$latest" "$version" "$latest" "$image" "$link" | cat - "$changelog" > "$changelog.tmp"
        mv "$changelog.tmp" "$changelog"
    else
        log "$COLOR_CYAN" "✅ $name is up to date"
        UNCHANGED_ADDONS["$name"]="Up to date ($version)"
    fi
}

commit_and_push() {
    cd "$REPO_DIR"
    git config user.email "updater@local"
    git config user.name "Add-on Updater"

    if [[ -n "$(git status --porcelain)" ]]; then
        git add . && git commit -m "🔄 Updated add-on versions" || return
        [[ "$SKIP_PUSH" == "true" ]] && return
        git push "$GIT_AUTH_REPO" main || log "$COLOR_RED" "❌ Git push failed"
    else
        log "$COLOR_CYAN" "ℹ️ No changes to commit"
    fi
}

main() {
    echo "" > "$LOG_FILE"
    read_config
    log "$COLOR_BLUE" "ℹ️ Starting Home Assistant Add-on Updater"
    git clone --depth 1 "$GIT_AUTH_REPO" "$REPO_DIR" || {
        log "$COLOR_RED" "❌ Git clone failed"
        notify "Updater Error" "Git clone failed" 5
        exit 1
    }

    for path in "$REPO_DIR"/*; do
        [[ -d "$path" ]] && update_addon "$path"
    done

    commit_and_push

    local summary="Add-on Update Summary\n\n"
    if [[ ${#UPDATED_ADDONS[@]} -gt 0 ]]; then
        summary+="✅ ${#UPDATED_ADDONS[@]} updated:\n"
        for k in "${!UPDATED_ADDONS[@]}"; do summary+="- $k: ${UPDATED_ADDONS[$k]}\n"; done
    fi
    summary+="\n"
    if [[ ${#UNCHANGED_ADDONS[@]} -gt 0 ]]; then
        summary+="ℹ️ ${#UNCHANGED_ADDONS[@]} unchanged:\n"
        for k in "${!UNCHANGED_ADDONS[@]}"; do summary+="- $k: ${UNCHANGED_ADDONS[$k]}\n"; done
    fi
    [[ "$DRY_RUN" == "true" ]] && summary+="\n🔁 DRY RUN MODE ENABLED"

    notify "Add-on Updater" "$summary" 3
    log "$COLOR_BLUE" "ℹ️ Update process complete."
}

main