#!/usr/bin/env bash

set -euo pipefail

ADDONS_DIR="/data/homeassistant"
CURRENT_ARCH=$(uname -m)
if [[ "$CURRENT_ARCH" == "x86_64" ]]; then CURRENT_ARCH="amd64"; fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

fetch_latest_tag() {
  local image=$1

  # Normalize image name if needed
  image=${image#docker.io/}
  image=${image#lscr.io/}
  image=${image#ghcr.io/}

  if [[ "$image" == *"/"* ]]; then
    local repo="${image%%:*}"
  else
    local repo="library/$image"
  fi

  local tag="${image##*:}"
  [[ "$tag" == "$image" ]] && tag="latest"

  # Docker Hub only (public unauthenticated)
  if [[ "$repo" == "linuxserver/"* || "$repo" == "library/"* || "$repo" == *"zoraxy"* || "$repo" == *"yoryan"* ]]; then
    curl -s "https://hub.docker.com/v2/repositories/${repo}/tags/?page_size=1" |
      jq -r '.results[0].name // "latest"'
  else
    echo "latest"
  fi
}

update_addon_if_needed() {
  local addon_dir=$1
  local addon_name
  addon_name=$(basename "$addon_dir")

  local config_file="$addon_dir/config.json"
  local build_file="$addon_dir/build.json"
  local image=""

  if [ -f "$build_file" ]; then
    image=$(jq -r --arg arch "$CURRENT_ARCH" '.build_from[$arch] // .build_from.amd64 // empty' "$build_file")
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi

  if [ -z "$image" ]; then
    log "Addon at $addon_dir has no Docker image defined, skipping."
    return
  fi

  log "Checking image: $image"
  local current_version
  current_version=$(jq -r '.version // empty' "$config_file")

  local latest_tag
  latest_tag=$(fetch_latest_tag "$image")

  if [[ "$current_version" == *"$latest_tag"* ]]; then
    echo "Addon '$addon_name' is already up-to-date ✔"
    return
  fi

  local new_version="v${latest_tag}"

  # Update config.json version
  jq --arg ver "$new_version" '.version = $ver' "$config_file" >"$config_file.tmp" && mv "$config_file.tmp" "$config_file"
  log "Updated $addon_name to version $new_version ✅"

  # Update CHANGELOG.md
  local changelog_url="https://github.com/linuxserver/docker-${addon_name}/releases"
  if ! grep -q "^v${latest_tag}" "$addon_dir/CHANGELOG.md" 2>/dev/null; then
    echo -e "\nv${new_version} ($(date '+%d-%m-%Y'))\n\nUpdate to latest version from $image (changelog: $changelog_url)" >>"$addon_dir/CHANGELOG.md"
  fi
}

log "🔄 Starting Docker image version check..."

for addon in "$ADDONS_DIR"/*/; do
  [ -d "$addon" ] || continue
  update_addon_if_needed "$addon"
done

NEXT_RUN=$(date -d "+1 day 03:00" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "unknown")
log "📅 Next check scheduled at 03:00 tomorrow (${NEXT_RUN})"
