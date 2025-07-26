#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

if [ ! -f "$CONFIG_PATH" ]; then
  echo "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")

clone_or_update_repo() {
  echo "Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    echo "Repository not found locally. Cloning..."
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR"
    else
      git clone "$GITHUB_REPO" "$REPO_DIR"
    fi
    echo "Repository cloned successfully."
  else
    echo "Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull
    echo "Repository updated."
  fi
}

get_latest_docker_tag() {
  local repo="$1"
  local tag=""
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=5&ordering=last_updated"

  echo "Fetching Docker tags from: $url" >&2  # debug output to stderr

  tag=$(curl -s "$url" | jq -r '.results[] | select(.name != "latest") | .name' | head -n 1)

  if [ -z "$tag" ]; then
    tag=$(curl -s "$url" | jq -r '.results[0].name')
  fi

  if [ -z "$tag" ] || [ "$tag" = "null" ]; then
    echo ""
  else
    echo "$tag"
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local changelog_file="$addon_path/CHANGELOG.md"
  local slug
  slug=$(basename "$addon_path")

  # Check if config.json exists and version is non-empty (indicates docker image addon)
  if [ ! -f "$config_file" ]; then
    echo "No config.json found in $addon_path, skipping updater.json creation."
    return
  fi

  local config_version
  config_version=$(jq -r '.version // empty' "$config_file")

  if [ -z "$config_version" ]; then
    echo "Addon '$slug' has empty version in config.json, assuming no docker image, skipping updater.json creation."
    return
  fi

  if [ ! -f "$updater_file" ]; then
    echo "No updater.json found in $addon_path, creating one with defaults..."
    cat > "$updater_file" << EOF
{
  "slug": "$slug",
  "upstream_repo": "",
  "upstream_version": "",
  "last_update": "Never"
}
EOF
  fi

  local upstream_repo
  upstream_repo=$(jq -r '.upstream_repo' "$updater_file")
  local current_version
  current_version=$(jq -r '.upstream_version' "$updater_file")
  local last_update
  last_update=$(jq -r '.last_update // "Never"' "$updater_file")

  if [ -z "$upstream_repo" ]; then
    echo "No 'upstream_repo' set in updater.json for $slug, skipping update check."
    echo "----------------------------"
    return
  fi

  local latest_version
  latest_version=$(get_latest_docker_tag "$upstream_repo")

  if [ -z "$latest_version" ]; then
    echo "Could not fetch latest docker tag for repo $upstream_repo"
    echo "Skipping update check for $slug due to missing latest tag."
    echo "----------------------------"
    return
  fi

  local now_datetime
  now_datetime=$(date '+%d-%m-%Y %H:%M')

  echo "----------------------------"
  echo "Addon: $slug"
  echo -e "${YELLOW}Last updated: $last_update${NC}"
  echo "Current Docker version: $current_version"
  echo "Latest Docker version:  $latest_version"

  if [ "$latest_version" != "$current_version" ]; then
    jq --arg v "$latest_version" --arg dt "$now_datetime" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"

    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
      echo -e "${GREEN}Updated config.json version to $latest_version${NC}"
    else
      echo "No config.json found in $addon_path"
    fi

    if [ ! -f "$changelog_file" ]; then
      touch "$changelog_file"
      echo "Created new CHANGELOG.md"
    fi

    {
      echo "v$latest_version ($now_datetime)"
      echo ""
      echo "    Update to latest version from $upstream_repo (changelog : https://github.com/${upstream_repo#*/}/releases)"
      echo ""
    } >> "$changelog_file"

    echo -e "${GREEN}Addon '$slug' updated to $latest_version ⬆️${NC}"
  else
    echo -e "${BLUE}Addon '$slug' is already up-to-date ✔${NC}"
  fi
  echo "----------------------------"
}

perform_update_check() {
  clone_or_update_repo
  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done
}

LAST_RUN_FILE="/data/last_run_date.txt"

echo "Performing initial update check on startup..."

perform_update_check

echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"
echo "Initial update check complete."

while true; do
  TODAY=$(date +%Y-%m-%d)
  CURRENT_TIME=$(date +%H:%M)

  LAST_RUN=""
  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$CURRENT_TIME" = "$CHECK_TIME" ] && [ "$LAST_RUN" != "$TODAY" ]; then
    echo "Running scheduled update checks at $CURRENT_TIME on $TODAY"
    perform_update_check
    echo "$TODAY" > "$LAST_RUN_FILE"
    echo "Scheduled update checks complete."
    echo -e "${CYAN}Next scheduled update check will run at $CHECK_TIME tomorrow.${NC}"
    sleep 60
  else
    sleep 30
  fi
done

