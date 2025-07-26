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
      jq -r '.results[0].name //
