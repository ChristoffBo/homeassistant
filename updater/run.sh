#!/usr/bin/env bash
set -e

REPO_DIR="/data/homeassistant"
CONFIG_FILE="config.json"
UPDATER_FILE="updater.json"
CHANGELOG_FILE="CHANGELOG.md"

LOG() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Portable next check time calculation (handles GNU date and BusyBox)
get_next_check_time() {
  if NEXT_CHECK=$(date -d '+1 hour' '+%H:%M %d-%m-%Y' 2>/dev/null); then
    echo "$NEXT_CHECK"
  else
    # BusyBox fallback: add 3600 seconds to epoch
    if NEXT_CHECK=$(date -u -D '%s' -d "$(( $(date +%s) + 3600 ))" '+%H:%M %d-%m-%Y' 2>/dev/null); then
      echo "$NEXT_CHECK"
    elif NEXT_CHECK=$(date -u -d "@$(( $(date +%s) + 3600 ))" '+%H:%M %d-%m-%Y' 2>/dev/null); then
      echo "$NEXT_CHECK"
    else
      echo "unknown time"
    fi
  fi
}

# Update changelog function - always prepend
update_changelog() {
  local addon_dir="$1"
  local version_from="$2"
  local version_to="$3"
  local changelog_path="$addon_dir/$CHANGELOG_FILE"
  local entry="v$version_to ($(date '+%d-%m-%Y'))\n\n    Updated from version $version_from to $version_to\n\n"

  if [[ ! -f "$changelog_path" ]]; then
    echo -e "$entry" > "$changelog_path"
  else
    # Prepend new entry to existing changelog
    local old_content
    old_content=$(cat "$changelog_path")
    echo -e "$entry$old_content" > "$changelog_path"
  fi
}

# Main update process
cd "$REPO_DIR" || exit 1

LOG "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M:%S')"

LOG "Pulling latest changes..."
if git pull --rebase origin main; then
  LOG "Repository updated successfully."
else
  LOG "Initial git pull failed!"
fi

# Loop through all addons (assuming each addon is a folder with config.json)
for addon_dir in */; do
  # Skip if no config.json
  if [[ ! -f "$addon_dir/$CONFIG_FILE" ]]; then
    LOG "Config file missing for addon: ${addon_dir%/}. Skipping."
    continue
  fi

  LOG "Addon: ${addon_dir%/}"

  # Extract current version and image from config.json
  current_version=$(jq -r '.version // empty' "$addon_dir/$CONFIG_FILE")
  image=$(jq -r '.image // .image // empty' "$addon_dir/$CONFIG_FILE" || echo "")

  # Skip if no docker image defined
  if [[ -z "$image" || "$image" == "null" ]]; then
    LOG "Add-on '${addon_dir%/}' has no Docker image defined, skipping."
    LOG "----------------------------"
    continue
  fi

  LOG "Current version: $current_version"
  LOG "Image: $image"

  # Check latest tag from DockerHub or github (simulate here: replace with your actual checking logic)
  # For example, parse the image tag or fetch from DockerHub API or github releases

  # Dummy fetch latest version example (you will replace this with real fetch)
  latest_version="5.7.0"  # TODO: replace with real lookup logic

  LOG "Latest version available: $latest_version"

  if [[ "$current_version" == "$latest_version" ]]; then
    LOG "Add-on '${addon_dir%/}' is already up-to-date ✔"
    # Show last update time if updater.json exists
    if [[ -f "$addon_dir/$UPDATER_FILE" ]]; then
      last_update=$(jq -r '.last_update // empty' "$addon_dir/$UPDATER_FILE")
      [[ -n "$last_update" ]] && LOG "Last update: $last_update"
    fi
  else
    LOG "🔄 Updating add-on '${addon_dir%/}' from version '$current_version' to '$latest_version'"

    # Update config.json version
    jq --arg ver "$latest_version" '.version=$ver' "$addon_dir/$CONFIG_FILE" > "$addon_dir/tmp.json" && mv "$addon_dir/tmp.json" "$addon_dir/$CONFIG_FILE"

    # Update changelog
    update_changelog "$addon_dir" "$current_version" "$latest_version"
    LOG "CHANGELOG.md updated for ${addon_dir%/}"

    # Update updater.json with new last_update
    jq --arg dt "$(date '+%d-%m-%Y %H:%M')" '.last_update=$dt' "$addon_dir/$UPDATER_FILE" 2>/dev/null > "$addon_dir/tmp_updater.json" && mv "$addon_dir/tmp_updater.json" "$addon_dir/$UPDATER_FILE" || echo "{\"last_update\":\"$(date '+%d-%m-%Y %H:%M')\"}" > "$addon_dir/$UPDATER_FILE"

    LOG "updater.json updated for ${addon_dir%/} (was: $current_version, now: $latest_version)"
  fi

  LOG "----------------------------"
done

# Commit and push if any changes
if git diff-index --quiet HEAD --; then
  LOG "No changes to commit."
else
  git config user.email "updater@local"
  git config user.name "Addon Updater Bot"
  git commit -am "Automatic update: bump addon versions"
  if git push origin main; then
    LOG "Git push successful."
  else
    LOG "Git push failed."
  fi
fi

NEXT_CHECK=$(get_next_check_time)
LOG "📅 Next check scheduled at $NEXT_CHECK"
