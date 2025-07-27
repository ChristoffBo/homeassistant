#!/usr/bin/env bash
set -e

REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
NOW=$(date +"%d-%m-%Y %H:%M:%S")

# Load these from config or env
GIT_REPO_URL="https://github.com/ChristoffBo/homeassistant.git"
GIT_USERNAME="yourusername"
GIT_TOKEN="yourtoken"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

log() {
    echo -e "[$(date +"%Y-%m-%d %H:%M:%S")] $*" | tee -a "$LOG_FILE"
}

get_latest_docker_tag() {
    local image="$1"
    # Handle no slash (official images)
    local repo image_name
    if [[ "$image" == *"/"* ]]; then
        repo=$(echo "$image" | cut -d/ -f1)
        image_name=$(echo "$image" | cut -d/ -f2)
    else
        repo="library"
        image_name="$image"
    fi

    local tags_json
    tags_json=$(curl -s "https://registry.hub.docker.com/v2/repositories/$repo/$image_name/tags/?page_size=50")

    # Check if tags_json is empty or null
    if [[ -z "$tags_json" || "$tags_json" == "null" ]]; then
        echo "latest"
        return
    fi

    local tag
    tag=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null | grep -v latest | grep -E '^[0-9]+(\.[0-9]+)*' | head -n 1 || echo "")

    if [[ -z "$tag" ]]; then
        tag="latest"
    fi
    echo "$tag"
}

update_changelog() {
    local addon_dir="$1"
    local addon_name="$2"
    local from_version="$3"
    local to_version="$4"
    local changelog_file="$addon_dir/CHANGELOG.md"
    local date_str=$(date +"%d-%m-%Y")

    local entry="## $date_str - Updated from $from_version to $to_version

- Automatic version bump

"

    if [[ ! -f "$changelog_file" ]]; then
        echo -e "# Changelog for $addon_name\n\n$entry" > "$changelog_file"
        log "${GREEN}Created new CHANGELOG.md for $addon_name${NC}"
    else
        tmp_file=$(mktemp)
        echo -e "$entry" > "$tmp_file"
        cat "$changelog_file" >> "$tmp_file"
        mv "$tmp_file" "$changelog_file"
        log "${GREEN}Updated CHANGELOG.md for $addon_name${NC}"
    fi
}

update_config_version() {
    local addon_dir="$1"
    local new_version="$2"
    local config_file="$addon_dir/config.json"

    if [[ ! -f "$config_file" ]]; then
        log "${YELLOW}Warning: config.json not found in $addon_dir${NC}"
        return 1
    fi

    jq --arg ver "$new_version" '.version = $ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
}

update_addon() {
    local addon_dir="$1"
    local addon_name=$(basename "$addon_dir")

    log "----------------------------"
    log "Addon: $addon_name"

    local config_file="$addon_dir/config.json"
    if [[ ! -f "$config_file" ]]; then
        log "${YELLOW}Warning: config.json not found for $addon_name, skipping.${NC}"
        return
    fi

    # Current version
    local current_version
    current_version=$(jq -r '.version // empty' "$config_file" | tr -d '"')

    # Image field might be missing or null
    local image
    image=$(jq -r '.image // empty' "$config_file")
    if [[ -z "$image" ]]; then
        # fallback: try url (not ideal but some add-ons may store image there)
        image=$(jq -r '.url // empty' "$config_file")
        # Skip if no valid Docker image (check if image contains a slash)
        if [[ -z "$image" || "$image" != *"/"* ]]; then
            log "Add-on '$addon_name' has no Docker image defined or invalid image field, skipping."
            return
        fi
    fi

    # Fetch latest tag from Docker Hub
    local latest_version
    latest_version=$(get_latest_docker_tag "$image")

    log "Current version: ${current_version:-<none>}"
    log "Latest version available: $latest_version"

    if [[ "$current_version" == "$latest_version" ]]; then
        log "Add-on '$addon_name' is already up-to-date ✔"
        return
    fi

    # Update config.json version field
    update_config_version "$addon_dir" "$latest_version"

    # Update changelog
    update_changelog "$addon_dir" "$addon_name" "${current_version:-none}" "$latest_version"

    log "🔄 Updating add-on '$addon_name' from version '${current_version:-none}' to '$latest_version'"
}

git_commit_and_push() {
    cd "$REPO_DIR"

    # Setup Git user if not set
    git config user.email "updater@example.com"
    git config user.name "Addon Updater Bot"

    # Set remote URL with token for auth
    local remote_url="https://${GIT_USERNAME}:${GIT_TOKEN}@github.com/ChristoffBo/homeassistant.git"
    git remote set-url origin "$remote_url"

    # Pull with rebase to avoid conflicts
    if ! git pull --rebase origin main; then
        log "${RED}Git pull failed${NC}"
    fi

    if [[ -n $(git status --porcelain) ]]; then
        git add .
        git commit -m "Automatic update: bump addon versions" --quiet
        if git push origin main --quiet; then
            log "${GREEN}Git push successful.${NC}"
        else
            log "${RED}Git push failed.${NC}"
        fi
    else
        log "No changes to commit."
    fi
}

main() {
    log "🚀 HomeAssistant Addon Updater started at $NOW"

    cd "$REPO_DIR"

    for addon_path in "$REPO_DIR"/*/; do
        [[ -d "$addon_path" ]] || continue
        update_addon "$addon_path"
    done

    git_commit_and_push

    # Schedule next check in 60 minutes without date arithmetic to avoid invalid date
    log "📅 Next check scheduled in 60 minutes."
}

main
