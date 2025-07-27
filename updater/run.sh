#!/usr/bin/env bash
set -euo pipefail

# ======= USER CONFIGURATION =======
GITHUB_REPO_URL="https://github.com/ChristoffBo/homeassistant"
GITHUB_USERNAME="your_username_here"
GITHUB_TOKEN="your_token_here"

# Directory where repo is cloned
REPO_DIR="/data/homeassistant"

# Time format for logs
TIMESTAMP() {
  date '+%Y-%m-%d %H:%M:%S'
}

log() {
  echo "[$(TIMESTAMP)] $*"
}

# Construct authenticated repo URL
AUTH_REPO_URL="${GITHUB_REPO_URL/https:\/\/github.com/https:\/\/${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com}"

cd "$REPO_DIR" || {
  log "ERROR: Repository directory $REPO_DIR does not exist."
  exit 1
}

# Pull latest changes with authentication
log "Pulling latest changes from repo..."
if git pull "$AUTH_REPO_URL" main; then
  log "Repository updated successfully."
else
  log "ERROR: Git pull failed."
  exit 1
fi

# Iterate over each addon folder
for ADDON_DIR in "$REPO_DIR"/*; do
  [ -d "$ADDON_DIR" ] || continue
  ADDON_NAME=$(basename "$ADDON_DIR")

  CONFIG_JSON="$ADDON_DIR/config.json"
  BUILD_JSON="$ADDON_DIR/build.json"
  UPDATER_JSON="$ADDON_DIR/updater.json"
  CHANGELOG_MD="$ADDON_DIR/CHANGELOG.md"

  if [ ! -f "$CONFIG_JSON" ]; then
    log "Config file missing for addon: $ADDON_NAME. Skipping."
    continue
  fi

  # Read current version from config.json
  CURRENT_VERSION=$(jq -r '.version // empty' "$CONFIG_JSON" || echo "")
  # Read image info from build.json or config.json
  IMAGE=$(jq -r '.image // empty' "$BUILD_JSON" 2>/dev/null || echo "")
  if [ -z "$IMAGE" ]; then
    IMAGE=$(jq -r '.image // empty' "$CONFIG_JSON" || echo "")
  fi

  if [ -z "$IMAGE" ]; then
    log "Add-on '$ADDON_NAME' has no Docker image defined, skipping."
    continue
  fi

  # Get image repo and tag
  IMAGE_REPO="${IMAGE%:*}"
  IMAGE_TAG="${IMAGE##*:}"
  [ "$IMAGE_TAG" = "$IMAGE_REPO" ] && IMAGE_TAG="latest"

  # Get latest tag from Docker Hub or linuxserver.io Github releases
  # This example fetches tags from Docker Hub (you can expand to github releases)
  # Here, only Docker Hub example:
  DOCKER_HUB_REPO="${IMAGE_REPO#*/}"  # Remove possible prefix like 'library/'
  DOCKER_HUB_REPO="${DOCKER_HUB_REPO,,}"  # lowercase

  # Extract repo name for docker hub API (for official images, adapt as needed)
  DOCKER_HUB_API="https://registry.hub.docker.com/v2/repositories/${IMAGE_REPO}/tags?page_size=10"

  # Fetch latest tag (basic, you might want more robust sorting or filter)
  LATEST_TAG=$(curl -s "$DOCKER_HUB_API" | jq -r '.results[0].name' || echo "latest")

  if [ -z "$LATEST_TAG" ]; then
    LATEST_TAG="latest"
  fi

  log "Addon: $ADDON_NAME"
  log "Current version: $CURRENT_VERSION"
  log "Image: $IMAGE_REPO:$IMAGE_TAG"
  log "Latest version available: $LATEST_TAG"

  if [ "$CURRENT_VERSION" = "$LATEST_TAG" ]; then
    log "Add-on '$ADDON_NAME' is already up-to-date ✔"
    log "----------------------------"
    continue
  fi

  # Update changelog: prepend new entry at top
  CHANGELOG_ENTRY="## [$LATEST_TAG] - $(date '+%Y-%m-%d')\n\n- Automatic update from version $CURRENT_VERSION to $LATEST_TAG\n"
  if [ ! -f "$CHANGELOG_MD" ]; then
    echo -e "$CHANGELOG_ENTRY" > "$CHANGELOG_MD"
    log "Created new CHANGELOG.md for $ADDON_NAME"
  else
    # Prepend changelog entry
    (echo -e "$CHANGELOG_ENTRY"; cat "$CHANGELOG_MD") > "$CHANGELOG_MD.tmp" && mv "$CHANGELOG_MD.tmp" "$CHANGELOG_MD"
    log "Updated CHANGELOG.md for $ADDON_NAME"
  fi

  # Update version in config.json to latest tag
  jq --arg ver "$LATEST_TAG" '.version = $ver' "$CONFIG_JSON" > "$CONFIG_JSON.tmp" && mv "$CONFIG_JSON.tmp" "$CONFIG_JSON"
  log "Updated config.json version for $ADDON_NAME to $LATEST_TAG"

  # Update or create updater.json with last_update info
  if [ -f "$UPDATER_JSON" ]; then
    jq --arg dt "$(date '+%Y-%m-%d %H:%M:%S')" '.last_update = $dt' "$UPDATER_JSON" > "$UPDATER_JSON.tmp" && mv "$UPDATER_JSON.tmp" "$UPDATER_JSON"
  else
    echo "{\"last_update\":\"$(date '+%Y-%m-%d %H:%M:%S')\"}" > "$UPDATER_JSON"
  fi
  log "updater.json updated for $ADDON_NAME"

done

# Commit and push changes
git add .
if git diff-index --quiet HEAD --; then
  log "No changes to commit."
else
  git commit -m "Automatic update: bump addon versions"
  if git push "$AUTH_REPO_URL" main; then
    log "Git push successful."
  else
    log "Git push failed."
    exit 1
  fi
fi

NEXT_CHECK=$(date -d '+1 hour' '+%H:%M %d-%m-%Y' 2>/dev/null || date -v+1H '+%H:%M %d-%m-%Y')

log "📅 Next check scheduled at $NEXT_CHECK"

