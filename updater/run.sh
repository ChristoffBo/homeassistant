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
  echo -e "${color}$*${COLOR_RESET}"
  echo "$*" >> "$LOG_FILE"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

if [ -z "$GITHUB_REPO" ] || [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_TOKEN" ]; then
  log "$COLOR_RED" "ERROR: github_repo, github_username, and github_token must be set in options.json"
  exit 1
fi

# Prepare authenticated repo URL for git commands
GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")

clone_or_update_repo() {
  log "$COLOR_BLUE" "Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_BLUE" "Repository not found locally. Cloning..."
    git clone "$GIT_AUTH_REPO" "$REPO_DIR" >/dev/null 2>&1
    log "$COLOR_GREEN" "Repository cloned successfully."
  else
    log "$COLOR_BLUE" "Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull --ff-only >/dev/null 2>&1 || {
      log "$COLOR_RED" "Git pull failed. Please check repository state."
      exit 1
    }
    log "$COLOR_GREEN" "Repository updated."
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local retries=3
  local count=0
  local tag=""
  while [ $count -lt $retries ]; do
    tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
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
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&ordering=last_updated"
  local tag=$(curl -s "$url" | jq -r '.results[0].name' 2>/dev/null)
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
  local tag=$(echo "$tags_json" | jq -r '.tags[-1]' 2>/dev/null)
  if [ -n "$tag" ] && [ "$tag" != "null" ]; then
    echo "$tag"
  else
    echo ""
  fi
}

get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"

  # Map lscr.io/linuxserver/... to linuxserver/ for API
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
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file")
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file")
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" | tr -d '\n' | tr -d '"')
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file")
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "Addon: $slug"
  log "$COLOR_BLUE" "Current version: $current_version"
  log "$COLOR_BLUE" "Image: $image"

  local latest_version=$(get_latest_docker_tag "$image")
  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    log "$COLOR_YELLOW" "WARNING: Could not fetch latest docker tag for image $image"
    log "$COLOR_BLUE" "Latest version available: Checking..."
    log "$COLOR_BLUE" "Add-on '$slug' is already up-to-date ✔"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "Latest version available: $latest_version"

  if [ "$latest_version" != "$current_version" ]; then
    log "$COLOR_GREEN" "🔄 Updating add-on '$slug' from version '$current_version' to '$latest_version'"

    # Update updater.json
    if [ -f "$updater_file" ]; then
      jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
         '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
         jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
           '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
      mv "$updater_file.tmp" "$updater_file"
    else
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file"
    fi

    # Update config.json version field (string only, no extra characters)
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null && mv "$config_file.tmp" "$config_file"

    # Create or prepend CHANGELOG.md
    if [ ! -f "$changelog_file" ]; then
      echo "" > "$changelog_file"
      log "$COLOR_YELLOW" "Created new CHANGELOG.md for $slug"
    fi

    # Prepend changelog entry
    local changelog_entry="v$latest_version ($(date +'%d-%m-%Y %H:%M'))\n\n    Update from $current_version to $latest_version\n\n"
    # Use temp file for prepend
    echo -e "$changelog_entry$(cat "$changelog_file")" > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"
    log "$COLOR_GREEN" "CHANGELOG.md updated for $slug"

  else
    log "$COLOR_BLUE" "Add-on '$slug' is already up-to-date ✔"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo
  cd "$REPO_DIR"

  for addon_path in */; do
    update_addon_if_needed "$addon_path"
  done

  # Commit and push changes if any
  if [ "$(git status --porcelain)" ]; then
    git add . >/dev/null 2>&1
    if git commit -m "Automatic update: bump addon versions" >/dev/null 2>&1; then
      if git push "$GIT_AUTH_REPO" main >/dev/null 2>&1; then
        log "$COLOR_GREEN" "Git push successful."
      else
        log "$COLOR_RED" "Git push failed. Check your authentication and remote URL."
      fi
    else
      log "$COLOR_YELLOW" "No changes to commit (commit skipped)."
    fi
  else
    log "$COLOR_BLUE" "No changes to commit."
  fi
}

LAST_RUN_FILE="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')"
perform_update_check
echo "$(date +%Y-%m-%d)" > "$LAST_RUN_FILE"

while true; do
  NOW_TIME=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=""
  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$NOW_TIME" = "$CHECK_TIME" ]; then
    if [ "$LAST_RUN" != "$TODAY" ]; then
      log "$COLOR_GREEN" "⏰ Running scheduled update checks at $NOW_TIME on $TODAY"
      perform_update_check
      echo "$TODAY" > "$LAST_RUN_FILE"
      log "$COLOR_GREEN" "✅ Scheduled update checks complete."
      sleep 60
    else
      log "$COLOR_BLUE" "✅ Already ran update checks today at $LAST_RUN."
    fi
  else
    # Calculate next scheduled run time for info
    local NEXT_RUN_TIME=$(date -d "today $CHECK_TIME" +'%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME")
    log "$COLOR_BLUE" "📅 Next check scheduled at $NEXT_RUN_TIME"
  fi

  sleep 60
done
