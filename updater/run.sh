#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE=/data/updater.log

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Clear log at start
: > "$LOG_FILE"

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

# Validate config
if [[ -z "$GITHUB_REPO" || -z "$GITHUB_USERNAME" || -z "$GITHUB_TOKEN" ]]; then
  log "$COLOR_RED" "ERROR: github_repo, github_username or github_token missing in config."
  exit 1
fi

# Prepare authenticated repo URL for git commands
# If user enters url without .git at end, append it
if [[ "$GITHUB_REPO" != *.git ]]; then
  GITHUB_REPO="${GITHUB_REPO%.git}.git"
fi
AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")

git_configure_identity() {
  git config user.name "Updater Bot"
  git config user.email "updater@local"
}

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "Cloning repository..."
    git clone "$AUTH_REPO" "$REPO_DIR" || {
      log "$COLOR_RED" "Failed to clone repository."
      exit 1
    }
    cd "$REPO_DIR"
    git_configure_identity
  else
    log "$COLOR_BLUE" "Repository exists, pulling latest..."
    cd "$REPO_DIR"
    git_configure_identity
    git pull --rebase || {
      log "$COLOR_YELLOW" "Git pull had issues, trying to stash and pull again."
      git stash save -u "Auto stash before pull"
      git pull --rebase || {
        log "$COLOR_RED" "Git pull failed after stash. Aborting."
        exit 1
      }
      git stash pop || true
    }
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=10&ordering=last_updated"
  local retries=3
  local count=0
  local tag=""
  while [ $count -lt $retries ]; do
    tag=$(curl -s "$url" | jq -r '.results[].name' 2>/dev/null | grep -v 'latest' | head -n1)
    if [ -n "$tag" ] && [ "$tag" != "null" ]; then
      echo "$tag"
      return 0
    fi
    count=$((count+1))
    sleep $((count * 2))
  done
  echo ""
}

fetch_latest_linuxserver_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=10&ordering=last_updated"
  local tag=$(curl -s "$url" | jq -r '.results[].name' 2>/dev/null | grep -v 'latest' | head -n1)
  if [ -n "$tag" ] && [ "$tag" != "null" ]; then
    echo "$tag"
  else
    echo ""
  fi
}

fetch_latest_ghcr_tag() {
  local image="$1"
  local repo_path="${image#ghcr.io/}"
  local url="https://ghcr.io/v2/${repo_path}/tags/list"
  local tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null)
  local tag=$(echo "$tags_json" | jq -r '.tags[]' 2>/dev/null | grep -v 'latest' | tail -n1)
  if [ -n "$tag" ] && [ "$tag" != "null" ]; then
    echo "$tag"
  else
    echo ""
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"

  # Fix for lscr.io/linuxserver/ images to map to linuxserver/ on Docker Hub API
  if [[ "$image_no_tag" == lscr.io/linuxserver/* ]]; then
    image_no_tag="${image_no_tag#lscr.io/}"
  fi

  if [[ "$image_no_tag" == linuxserver/* ]]; then
    echo "$(fetch_latest_linuxserver_tag "$image_no_tag")"
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    echo "$(fetch_latest_ghcr_tag "$image_no_tag")"
  else
    echo "$(fetch_latest_dockerhub_tag "$image_no_tag")"
  fi
}

sanitize_version() {
  echo "$1" | tr -d '\n' | tr -d '\r' | tr -d '"' | xargs
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "Add-on '$(basename "$addon_path")' has no config.json or build.json, skipping."
    return
  fi

  local image=""
  local slug=""
  local current_version=""
  local latest_version=""

  # Determine image and slug
  if [ -f "$build_file" ]; then
    # Attempt to get arch specific or amd64 image
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file")
    slug=$(jq -r '.slug // empty' "$build_file")
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
    slug=$(jq -r '.slug // empty' "$config_file")
  fi

  if [ -z "$slug" ]; then
    slug=$(basename "$addon_path")
  fi

  # Read current version from updater.json or config.json
  if [ -f "$updater_file" ]; then
    current_version=$(jq -r '.upstream_version // empty' "$updater_file")
  fi
  if [ -z "$current_version" ] && [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file")
  fi
  current_version=$(sanitize_version "$current_version")

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "Add-on '$slug' has no Docker image defined, skipping."
    return
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "Addon: $slug"
  log "$COLOR_BLUE" "Current version: $current_version"
  log "$COLOR_BLUE" "Image: $image"

  # Get latest version tag (non-latest)
  latest_version=$(get_latest_docker_tag "$image")
  latest_version=$(sanitize_version "$latest_version")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "WARNING: Could not fetch latest docker tag for image $image"
    log "$COLOR_BLUE" "Latest version: unknown"
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "Latest version available: $latest_version"

  # Only update if versions differ and latest_version is not empty or 'latest'
  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "🔄 Updating add-on '$slug' from version '$current_version' to '$latest_version'"

    # Update updater.json
    if [ -f "$updater_file" ]; then
      jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
        '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
        jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
          '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
      mv "$updater_file.tmp" "$updater_file"
    else
      echo "{\"slug\":\"$slug\",\"image\":\"$image\",\"upstream_version\":\"$latest_version\",\"last_update\":\"$(date +'%d-%m-%Y %H:%M')\"}" > "$updater_file"
    fi

    # Update config.json version field with clean version
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    # Create CHANGELOG.md if missing
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $slug" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "Created new CHANGELOG.md for $slug"
    fi

    # Append changelog entry
    {
      echo ""
      echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))"
      echo "    Update from version $current_version to $latest_version (image: $image)"
      echo ""
    } >> "$changelog_file"
    log "$COLOR_GREEN" "CHANGELOG.md updated for $slug"

  else
    log "$COLOR_BLUE" "Addon '$slug' is already up-to-date ✔"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  for addon_path in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon_path"
  done
}

push_changes() {
  cd "$REPO_DIR"
  if git diff-index --quiet HEAD --; then
    log "$COLOR_BLUE" "No changes to commit."
  else
    git add .
    git commit -m "Automatic update: bump addon versions"
    if git push "$AUTH_REPO" HEAD; then
      log "$COLOR_GREEN" "Git push successful."
    else
      log "$COLOR_RED" "Git push failed. Check authentication and remote URL."
    fi
  fi
}

# Run update on start
log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')"
perform_update_check
push_changes

LAST_RUN_FILE="/data/last_run_date.txt"
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

while true; do
  NOW_TIME=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=""

  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$NOW_TIME" == "$CHECK_TIME" ] || [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_TIME on $TODAY"
    perform_update_check
    push_changes
    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."
    sleep 60  # prevent multiple runs in the same minute
  else
    # Calculate next scheduled check time for info
    CURRENT_SEC=$(date +%s)
    CHECK_HOUR=${CHECK_TIME%%:*}
    CHECK_MIN=${CHECK_TIME##*:}
    TODAY_SEC=$(date -d "$(date +%Y-%m-%d)" +%s 2>/dev/null || echo 0)
    if [ "$TODAY_SEC" -eq 0 ]; then
      NEXT_CHECK_TIME="$CHECK_TIME (date command not supported)"
    else
      CHECK_SEC=$((TODAY_SEC + CHECK_HOUR * 3600 + CHECK_MIN * 60))
      if [ "$CURRENT_SEC" -ge "$CHECK_SEC" ]; then
        TOMORROW_SEC=$((TODAY_SEC + 86400))
        NEXT_CHECK_TIME=$(date -d "@$((TOMORROW_SEC + CHECK_HOUR * 3600 + CHECK_MIN * 60))" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
      else
        NEXT_CHECK_TIME=$(date -d "@$CHECK_SEC" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
      fi
    fi
    log "$COLOR_BLUE" "📅 Next check scheduled at $NEXT_CHECK_TIME"
  fi

  sleep 60
done
