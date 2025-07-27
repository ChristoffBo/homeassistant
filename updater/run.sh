#!/usr/bin/env bash
set -e

# Colors for output
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
NC="\033[0m" # No Color

REPO_DIR="/data/homeassistant"
GIT_USERNAME="${GIT_USERNAME:-your_username}"
GIT_TOKEN="${GIT_TOKEN:-your_token}"
GIT_REPO_URL="https://github.com/ChristoffBo/homeassistant"

log() {
  local color="$1"
  shift
  echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] $*${NC}"
}

# Ensure repository cloned
if [ ! -d "$REPO_DIR/.git" ]; then
  log "$YELLOW" "Cloning repository..."
  git clone "$GIT_REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"

# Function to update repo with rebase fallback to merge
git_pull_latest() {
  git config user.email "updater@example.com"
  git config user.name "Addon Updater Bot"
  local remote_url="https://${GIT_USERNAME}:${GIT_TOKEN}@github.com/ChristoffBo/homeassistant.git"
  git remote set-url origin "$remote_url"

  log "$YELLOW" "Pulling latest changes..."
  if ! git pull --rebase origin main; then
    log "$RED" "Rebase failed due to diverging branches, trying merge..."
    if ! git merge origin/main --no-ff; then
      log "$RED" "Git merge also failed. Manual intervention required."
      return 1
    fi
  fi
  log "$GREEN" "Repository updated."
}

# Append changelog entry at top of CHANGELOG.md (create if missing)
update_changelog() {
  local addon=$1
  local old_ver=$2
  local new_ver=$3
  local changelog_file="${REPO_DIR}/${addon}/CHANGELOG.md"
  local date_now
  date_now=$(date '+%Y-%m-%d')

  local new_entry="## [$new_ver] - $date_now
- Updated from $old_ver to $new_ver

"

  if [ ! -f "$changelog_file" ]; then
    echo -e "$new_entry" > "$changelog_file"
    log "$GREEN" "Created new CHANGELOG.md for $addon"
  else
    # Prepend changelog entry
    tmpfile=$(mktemp)
    echo -e "$new_entry" > "$tmpfile"
    cat "$changelog_file" >> "$tmpfile"
    mv "$tmpfile" "$changelog_file"
    log "$GREEN" "CHANGELOG.md updated for $addon"
  fi
}

# Update version in config.json
update_version_in_config() {
  local addon=$1
  local new_ver=$2
  local config_file="${REPO_DIR}/${addon}/config.json"

  if [ -f "$config_file" ]; then
    # Use jq to update version (if jq not available fallback)
    if command -v jq >/dev/null 2>&1; then
      tmpfile=$(mktemp)
      jq --arg ver "$new_ver" '.version = $ver' "$config_file" > "$tmpfile" && mv "$tmpfile" "$config_file"
    else
      # fallback: sed (assumes "version": "..." in one line)
      sed -i "s/\"version\": *\"[^\"]*\"/\"version\": \"$new_ver\"/" "$config_file"
    fi
    log "$GREEN" "Updated config.json version for $addon to $new_ver"
  else
    log "$RED" "Config file not found for $addon"
  fi
}

# Main update function for an addon
update_addon() {
  local addon=$1
  local config_file="${REPO_DIR}/${addon}/config.json"
  local current_ver
  local image_tag
  local latest_ver

  if [ ! -f "$config_file" ]; then
    log "$RED" "Config file missing for addon: $addon. Skipping."
    return
  fi

  # Get current version from config.json
  current_ver=$(jq -r '.version // empty' "$config_file")
  # Get image repo from config.json (assumes image key exists)
  image_tag=$(jq -r '.image // empty' "$config_file")

  if [ -z "$image_tag" ] || [ "$image_tag" == "null" ]; then
    # fallback to .image_repo or manual assignment (adjust this to your structure)
    image_tag=$(jq -r '.image_repo // empty' "$config_file")
  fi

  if [ -z "$image_tag" ]; then
    log "$YELLOW" "Add-on '$addon' has no Docker image defined, skipping."
    return
  fi

  # Query Dockerhub or GitHub or linuxserver.io for latest tag:
  # For simplicity, here we get latest tag from dockerhub (adjust as needed)
  latest_ver=$(curl -s "https://registry.hub.docker.com/v2/repositories/${image_tag}/tags?page_size=1" \
                | jq -r '.results[0].name // empty')

  if [ -z "$latest_ver" ]; then
    latest_ver="latest"
  fi

  log "$YELLOW" "Addon: $addon"
  log "$YELLOW" "Current version: $current_ver"
  log "$YELLOW" "Latest version available: $latest_ver"

  if [ "$current_ver" != "$latest_ver" ]; then
    log "$YELLOW" "🔄 Updating add-on '$addon' from version '$current_ver' to '$latest_ver'"
    update_changelog "$addon" "$current_ver" "$latest_ver"
    update_version_in_config "$addon" "$latest_ver"
  else
    log "$GREEN" "Add-on '$addon' is already up-to-date ✔"
  fi

  echo "----------------------------"
}

# Commit and push changes
git_commit_and_push() {
  cd "$REPO_DIR"

  if [[ -n $(git status --porcelain) ]]; then
    git add .
    git commit -m "Automatic update: bump addon versions" --quiet
    if git push origin main --quiet; then
      log "$GREEN" "Git push successful."
    else
      log "$RED" "Git push failed."
    fi
  else
    log "No changes to commit."
  fi
}

# Run full update process
run_update() {
  log "$GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M:%S')"

  if ! git_pull_latest; then
    log "$RED" "Initial git pull failed! Aborting update."
    return 1
  fi

  # List all addon directories (adjust path and criteria if needed)
  local addons
  addons=$(find "$REPO_DIR" -maxdepth 1 -mindepth 1 -type d -exec basename {} \;)

  for addon in $addons; do
    update_addon "$addon"
  done

  git_commit_and_push

  log "$GREEN" "📅 Next check scheduled at $(date -d '+1 hour' '+%H:%M %d-%m-%Y')"
}

run_update
