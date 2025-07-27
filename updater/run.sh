#!/usr/bin/env bash
set -e

REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
NOW=$(date +"%d-%m-%Y %H:%M:%S")
GIT_REPO_URL="https://github.com/ChristoffBo/homeassistant.git"
GIT_USERNAME="yourusername"    # from config
GIT_TOKEN="yourtoken"          # from config

# Colored output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Helper: print log with timestamp
log() {
    echo -e "[$(date +"%Y-%m-%d %H:%M:%S")] $*" | tee -a "$LOG_FILE"
}

# Helper: fetch latest Docker tag (non-latest) for given image
get_latest_docker_tag() {
    local image="$1"
    # Extract repo and image parts
    # For example: alexta69/metube -> alexta69/metube
    # Use Docker Hub API v2 to fetch tags sorted by last_updated
    # Exclude "latest"
    local repo image_name
    repo=$(echo "$image" | cut -d/ -f1)
    image_name=$(echo "$image" | cut -d/ -f2)
    # Fallback if no slash
    if [[ "$image" != *"/"* ]]; then
        repo="library"
        image_name="$image"
    fi

    # Fetch tags sorted by last_updated descending
    local tags_json
    tags_json=$(curl -s "https://registry.hub.docker.com/v2/repositories/$repo/$image_name/tags/?page_size=50")

    # Extract the first tag name that is NOT "latest" and matches semantic version pattern
    local tag
    tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v latest | grep -E '^[0-9]+(\.[0-9]+)*' | head -n 1)

    if [[ -z "$tag" ]]; then
        # fallback to latest if no proper tag found
        tag="latest"
    fi

    echo "$tag"
}

# Update changelog: prepend new entry at top
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
        # Prepend entry
        tmp_file=$(mktemp)
        echo -e "$entry" > "$tmp_file"
        cat "$changelog_file" >> "$tmp_file"
        mv "$tmp_file" "$changelog_file"
        log "${GREEN}Updated CHANGELOG.md for $addon_name${NC}"
    fi
}

# Update config.json version field
update_config_version() {
    local addon_dir="$1"
    local new_version="$2"
    local config_file="$addon_dir/config.json"

    # Use jq to update "version" field exactly
    jq --arg ver "$new_version" '.version=$ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
}

# Main update logic for one addon
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

    # Extract current version
    local current_version
    current_version=$(jq -r '.version' "$config_file" | tr -d '"')

    # Extract image name if present
    local image
    image=$(jq -r '.image // empty' "$config_file")
    if [[ -z "$image" ]]; then
        # try "image" key in config or "url" - you may adjust here
        # Some add-ons use "image" or "image" key; if none skip
        image=$(jq -r '.url // empty' "$config_file")
        if [[ -z "$image" ]]; then
            log "Addon '$addon_name' has no Docker image defined, skipping."
            return
        fi
    fi

    # Get actual latest version tag from Docker Hub
    local latest_version
    latest_version=$(get_latest_docker_tag "$image")

    log "Current version: $current_version"
    log "Latest version available: $latest_version"

    if [[ "$current_version" == "$latest_version" ]]; then
        log "Add-on '$addon_name' is already up-to-date ✔"
        return
    fi

    # Update config.json version
    update_config_version "$addon_dir" "$latest_version"

    # Update changelog
    update_changelog "$addon_dir" "$addon_name" "$current_version" "$latest_version"

    log "🔄 Updating add-on '$addon_name' from version '$current_version' to '$latest_version'"
}

# Git commit and push changes
git_commit_and_push() {
    cd "$REPO_DIR"

    # Git pull first to avoid conflicts
    git pull origin main --ff-only || log "${RED}Git pull failed!${NC}"

    # Check if any changes
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

# MAIN
log "🚀 HomeAssistant Addon Updater started at $NOW"

cd "$REPO_DIR"

# Pull latest from repo to start clean
git pull origin main --ff-only || log "${RED}Initial git pull failed!${NC}"

for addon_path in "$REPO_DIR"/*/; do
    # Only directories
    [[ -d "$addon_path" ]] || continue
    update_addon "$addon_path"
done

git_commit_and_push

log "📅 Next check scheduled at $(date -d "+1 hour" +"%H:%M %d-%m-%Y")"
