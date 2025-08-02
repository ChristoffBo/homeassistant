#!/bin/sh
set -e

# Start time tracking
START_TIME=$(date +%s)

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Timezone setting
TZ=$(jq -r '.TZ // "Africa/Johannesburg"' /data/options.json)
export TZ

# Log functions
log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }
section() { echo -e "\n${CYAN}==> $1${NC}"; }

# Load config
CONFIG_FILE="/data/options.json"
ADDONS_DIR="/addons"
TZ=$(jq -r '.TZ // "Africa/Johannesburg"' "$CONFIG_FILE")
NOTIFIER=$(jq -r '.notifier // empty' "$CONFIG_FILE")
CRON_TIME=$(jq -r '.check_time // "0 3 * * *"' "$CONFIG_FILE")

# Notification function
notify_update() {
  local message="$1"
  case "$NOTIFIER" in
    gotify*)
      url=$(jq -r '.gotify_url' "$CONFIG_FILE")
      token=$(jq -r '.gotify_token' "$CONFIG_FILE")
      curl -s -X POST "$url/message?token=$token" \
        -F "title=Add-on Update" -F "message=$message" -F "priority=5" >/dev/null
      ;;
    apprise*)
      url=$(jq -r '.apprise_url' "$CONFIG_FILE")
      curl -s "$url" -d "$message" >/dev/null
      ;;
    mailrise*)
      url=$(jq -r '.mailrise_url' "$CONFIG_FILE")
      curl -s -X POST "$url" -H "Content-Type: text/plain" -d "$message" >/dev/null
      ;;
    *)
      warn "Notifier not set or unsupported"
      ;;
  esac
}

# Get image tag from Docker Hub or GHCR
get_latest_tag() {
  local image="$1"
  local repo repo_api tag
  case "$image" in
    *ghcr.io*)
      repo=$(echo "$image" | cut -d/ -f2-)
      tag=$(curl -fs "https://ghcr.io/v2/${repo}/tags/list" | jq -r '.tags[]' | grep -v latest | sort -V | tail -n1)
      ;;
    *linuxserver/*)
      repo=$(echo "$image" | cut -d/ -f2)
      tag=$(curl -fs "https://hub.docker.com/v2/repositories/linuxserver/${repo}/tags" | jq -r '.results[].name' | grep -v latest | sort -V | tail -n1)
      ;;
    *)
      repo=$(echo "$image" | cut -d/ -f2)
      tag=$(curl -fs "https://hub.docker.com/v2/repositories/${image}/tags" | jq -r '.results[].name' | grep -v latest | sort -V | tail -n1)
      ;;
  esac
  echo "$tag"
}

# Update JSON file with new tag
update_json_tag() {
  local file="$1" key="$2" new_tag="$3"
  if [ -f "$file" ]; then
    tmp=$(mktemp)
    jq ".$key = \"$new_tag\"" "$file" > "$tmp" && mv "$tmp" "$file"
    log "Updated $key in $file to $new_tag"
  else
    warn "$file not found to update"
  fi
}

# Add or update changelog
update_changelog() {
  local addon="$1" old="$2" new="$3"
  local changelog="$addon/CHANGELOG.md"
  local timestamp
  timestamp=$(TZ=$TZ date +"%Y-%m-%d %H:%M %Z")
  mkdir -p "$addon"
  echo -e "## [$new] - $timestamp\n- Updated from $old to $new\n" >> "$changelog"
  log "CHANGELOG.md updated in $addon"
}

# Process each addon
for addon in "$ADDONS_DIR"/*; do
  [ -d "$addon" ] || continue
  section "Checking: $(basename "$addon")"
  
  cd "$addon"

  # Pull repo if updater.json exists
  if [ -f updater.json ]; then
    repo_url=$(jq -r '.repo // empty' updater.json)
    branch=$(jq -r '.branch // "main"' updater.json)
    if [ -n "$repo_url" ]; then
      if [ -d .git ]; then
        git reset --hard
        git pull --quiet origin "$branch"
        log "Repo updated for $(basename "$addon")"
      else
        rm -rf "$addon/*"
        git clone --depth 1 --branch "$branch" "$repo_url" "$addon"
        log "Repo cloned for $(basename "$addon")"
      fi
    fi
  fi

  # Detect image
  image=$(grep -Eho 'image": *"[^"]+' config.json build.json updater.json Dockerfile 2>/dev/null | head -n1 | cut -d'"' -f2)
  if [ -z "$image" ]; then
    warn "No image found for $(basename "$addon")"
    continue
  fi

  # Get current and latest tag
  current_tag=$(echo "$image" | rev | cut -d: -f1 | rev)
  base_image=$(echo "$image" | cut -d: -f1)
  latest_tag=$(get_latest_tag "$base_image")

  log "Current: $current_tag | Latest: $latest_tag"

  if [ "$latest_tag" != "$current_tag" ] && [ -n "$latest_tag" ]; then
    log "Updating to $latest_tag"

    update_json_tag "config.json" "image" "$base_image:$latest_tag"
    update_json_tag "build.json" "image" "$base_image:$latest_tag"
    update_changelog "$addon" "$current_tag" "$latest_tag"

    git add .
    git config user.name "Updater"
    git config user.email "addon-updater@local"
    git commit -m "Update $(basename "$addon") to $latest_tag"
    git push -q

    curl -s -X POST http://supervisor/addons/reload
    notify_update "$(basename "$addon") updated from $current_tag to $latest_tag"
  else
    log "No update needed for $(basename "$addon")"
  fi
done

# Duration
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
section "Finished. Duration: ${ELAPSED}s"
