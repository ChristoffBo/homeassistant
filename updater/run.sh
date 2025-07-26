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
UPDATE_INTERVAL=$(jq -r '.update_interval_minutes' "$CONFIG_PATH")

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

  # Docker Hub tag fetch
  url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  tag=$(curl -s "$url" | jq -r '.results[0].name')

  echo "$tag"
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"

  if [ ! -f "$updater_file" ]; then
    echo "No updater.json found in $addon_path, skipping."
    return
  fi

  local upstream_repo=$(jq -r '.upstream_repo' "$updater_file")
  local upstream_version=$(jq -r '.upstream_version' "$updater_file")
  local slug=$(jq -r '.slug' "$updater_file")

  echo "Checking $slug against Docker Hub for updates..."

  latest_version=$(get_latest_docker_tag "$upstream_repo")

  if [ "$latest_version" != "$upstream_version" ] && [ "$latest_version" != "null" ]; then
    echo "Update available for $slug: $upstream_version -> $latest_version"
    jq --arg v "$latest_version" '.upstream_version = $v | .last_update = "'$(date +%d-%m-%Y)'"' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"
  else
    echo "$slug is up to date."
  fi
}

while true; do
  clone_or_update_repo

  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done

  echo "Sleeping for $UPDATE_INTERVAL minutes before next check..."
  sleep "$((UPDATE_INTERVAL * 60))"
done

