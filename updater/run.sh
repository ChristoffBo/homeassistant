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
  local image="$1"
  # Separate registry and repo:tag parts
  local registry=""
  local repo_tag="$image"

  if [[ "$image" == *"/"*"/"* ]]; then
    # image with registry: e.g. ghcr.io/user/repo:tag
    registry=$(echo "$image" | cut -d/ -f1)
    repo_tag=${image#*/}
  fi

  # Default tag
  local current_tag="latest"
  if [[ "$repo_tag" == *":"* ]]; then
    current_tag="${repo_tag##*:}"
    repo_tag="${repo_tag%:*}"
  fi

  # Handle Docker Hub (docker.io) and GHCR
  if [[ "$registry" == "" || "$registry" == "docker.io" ]]; then
    # Docker Hub API v2
    local url="https://registry.hub.docker.com/v2/repositories/$repo_tag/tags?page_size=1&ordering=last_updated"
    latest_tag=$(curl -s "$url" | jq -r '.results[0].name')
  elif [[ "$registry" == "ghcr.io" ]]; then
    # GitHub Container Registry API (public only, no auth)
    # repo_tag includes user/org and image name: user/image
    local gh_repo="$repo_tag"
    latest_tag=$(curl -s "https://ghcr.io/v2/$gh_repo/tags/list" | jq -r '.tags[-1]')
  else
    echo "Registry $registry not supported for auto tag lookup"
    latest_tag=""
  fi

  echo "$latest_tag"
}

update_addon_version() {
  local addon_path="$1"
  local config_file="$addon_path/config.json"

  local addon_name=$(basename "$addon_path")
  local current_version=$(jq -r '.version' "$config_file")
  local image=$(jq -r '.image' "$config_file")

  if [[ "$image" == "null" || -z "$image" ]]; then
    echo "Add-on '$addon_name' has no image field; skipping."
    return
  fi

  echo "Checking add-on '$addon_name' image '$image'..."

  latest_tag=$(get_latest_docker_tag "$image")

  if [[ -z "$latest_tag" || "$latest_tag" == "null" ]]; then
    echo "Could not determine latest tag for image '$image'."
    return
  fi

  if [[ "$current_version" != "$latest_tag" ]]; then
    echo "Updating add-on '$addon_name' version from '$current_version' to '$latest_tag'."
    # Update the version field in config.json
    jq --arg ver "$latest_tag" '.version=$ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
  else
    echo "Add-on '$addon_name' is already up to date (version $current_version)."
  fi
}

while true; do
  clone_or_update_repo

  # Iterate over add-ons folders
  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ]; then
      update_addon_version "$addon_path"
    fi
  done

  echo "Sleeping for $UPDATE_INTERVAL minutes before next check..."
  sleep "${UPDATE_INTERVAL}m"
done
