#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

if [ ! -f "$CONFIG_PATH" ]; then
  echo "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

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

  url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  tag=$(curl -s "$url" | jq -r '.results[0].name')

  echo "$tag"
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$updater_file" ]; then
    echo "No updater.json found in $addon_path, skipping."
    return
  fi

  local upstream_repo=$(jq -r '.upstream_repo' "$updater_file")
  local upstream_version=$(jq -r '.upstream_version' "$updater_file")
  local slug=$(jq -r '.slug' "$updater_file")

  # Fetch latest Docker tag
  local latest_version
  latest_version=$(get_latest_docker_tag "$upstream_repo")

  # Read current GitHub repo version from config.json if it exists
  local github_version="N/A"
  if [ -f "$config_file" ]; then
    github_version=$(jq -r '.version // empty' "$config_file")
    if [ -z "$github_version" ]; then
      github_version="N/A"
    fi
  fi

  echo "----------------------------"
  echo "Addon: $slug"
  echo "Current Docker version: $upstream_version"
  echo "Latest Docker version:  $latest_version"
  echo "Current GitHub version (config.json): $github_version"

  if [ "$latest_version" != "$upstream_version" ] && [ "$latest_version" != "null" ]; then
    echo "Update available: $upstream_version -> $latest_version"
    jq --arg v "$latest_version" --arg dt "$(date +%d-%m-%Y)" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"

    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
      echo "Updated config.json version to $latest_version"
    fi

    # Ensure CHANGELOG.md exists; create if missing
    if [ ! -f "$changelog_file" ]; then
      touch "$changelog_file"
      echo "Created new CHANGELOG.md"
    fi

    # Append changelog entry
    {
      echo "v$latest_version ($(date +%d-%m-%Y))"
      echo ""
      echo "    Update to latest version from $upstream_repo (changelog : https://github.com/${upstream_repo#*/}/releases)"
      echo ""
    } >> "$changelog_file"

    echo "CHANGELOG.md updated with version and changelog link."
  else
    echo "No update needed; already at latest version."
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

# Run one-time check immediately on start
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

    sleep 60  # avoid multiple runs in the same minute
  else
    sleep 30
  fi
done
