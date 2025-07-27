#!/usr/bin/env bash
set -euo pipefail

# Paths & constants
CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Colors for logging
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_BLUE="\033[0;34m"
COLOR_PURPLE="\033[0;35m"

# Load options
CRON_SCHEDULE=$(jq -r '.cron // "0 3 * * *"' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
GOTIFY_URL=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
GOTIFY_TOKEN=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
MAILRISE_URL=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
APPRISE_URL=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")

# Logging helper
log() {
  local color=$1
  shift
  echo -e "$(date -u +"[%Y-%m-%d %H:%M:%S UTC]") ${color}$*${COLOR_RESET}"
}

# Send notification (only if url and token provided)
send_notification() {
  local service=$1
  local message=$2

  case $service in
    gotify)
      if [[ -n "$GOTIFY_URL" && -n "$GOTIFY_TOKEN" ]]; then
        curl -s -X POST -H "X-Gotify-Key: $GOTIFY_TOKEN" -d "message=$message" "$GOTIFY_URL/message" >/dev/null 2>&1
      fi
      ;;
    mailrise)
      if [[ -n "$MAILRISE_URL" ]]; then
        curl -s -X POST -H "Content-Type: application/json" -d "{\"text\":\"$message\"}" "$MAILRISE_URL" >/dev/null 2>&1
      fi
      ;;
    apprise)
      if [[ -n "$APPRISE_URL" ]]; then
        curl -s -X POST -d "body=$message" "$APPRISE_URL" >/dev/null 2>&1
      fi
      ;;
  esac
}

# Calculate next run time in hours and minutes
next_run_time() {
  local cron="$1"
  local tz="$2"
  # Use date & cronutils if available, fallback to manual approx

  # Get next cron run timestamp in seconds
  local next_ts
  if command -v cronnext >/dev/null 2>&1; then
    next_ts=$(cronnext -t "$tz" "$cron" | head -n1)
  else
    # Approximate next run by parsing cron (only supports hh:mm * * *)
    local hour minute now_ts next_ts
    minute=$(echo "$cron" | awk '{print $1}')
    hour=$(echo "$cron" | awk '{print $2}')
    now_ts=$(TZ="$tz" date +%s)
    next_ts=$(TZ="$tz" date -d "today $hour:$minute" +%s)
    if (( next_ts <= now_ts )); then
      next_ts=$(TZ="$tz" date -d "tomorrow $hour:$minute" +%s)
    fi
  fi
  local now=$(TZ="$tz" date +%s)
  local diff=$((next_ts - now))
  if ((diff < 0)); then
    echo "Unknown"
    return
  fi
  local hours=$((diff / 3600))
  local mins=$(((diff % 3600) / 60))
  echo "${hours} hours ${mins} minutes"
}

# Function to get latest docker tag from Docker Hub
get_latest_dockerhub_tag() {
  local image=$1
  # Extract repo and image name (handle namespace)
  local repo="${image%%:*}"
  if [[ "$repo" == "$image" ]]; then
    repo="$image"
  fi
  # Remove tag if any
  repo="${repo%%:*}"

  # Query Docker Hub API for tags (limit to 1)
  local tags_json
  tags_json=$(curl -s "https://hub.docker.com/v2/repositories/${repo}/tags?page_size=5")
  if [[ -z "$tags_json" ]]; then
    echo "latest"
    return
  fi
  # Extract latest tag by date
  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '.results | sort_by(.last_updated) | last(.[]).name' 2>/dev/null || echo "latest")
  echo "${latest_tag:-latest}"
}

# Function to get latest tag from LinuxServer.io docker image
get_latest_linuxserver_tag() {
  local image=$1
  # Remove prefix if exists
  local image_name="${image##*/}"
  local url="https://registry.hub.docker.com/v2/repositories/lscr.io/linuxserver/${image_name}/tags?page_size=5"
  local tags_json
  tags_json=$(curl -s "$url")
  if [[ -z "$tags_json" ]]; then
    echo "latest"
    return
  fi
  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '.results | sort_by(.last_updated) | last(.[]).name' 2>/dev/null || echo "latest")
  echo "${latest_tag:-latest}"
}

# Function to get latest GitHub release tag (via API)
get_latest_github_tag() {
  local repo=$1
  # repo in format owner/repo
  local url="https://api.github.com/repos/${repo}/releases/latest"
  local tag
  tag=$(curl -s "$url" | jq -r '.tag_name // "latest"')
  echo "$tag"
}

# Read all addons directories (assume they are folders in $REPO_DIR)
addons_dirs=()
while IFS= read -r -d $'\0'; do
  addons_dirs+=("$REPLY")
done < <(find "$REPO_DIR" -mindepth 1 -maxdepth 1 -type d -print0)

# Pull latest repo
log "$COLOR_BLUE" "🔮 Pulling latest from GitHub repository..."
git -C "$REPO_DIR" pull origin main && log "$COLOR_GREEN" "✅ Git pull successful." || {
  log "$COLOR_RED" "❌ Git pull failed."
  exit 1
}

any_update=0
notify_messages=()

# Loop over addons
for addon_path in "${addons_dirs[@]}"; do
  # Read JSON files if exist
  config_json=""
  build_json=""
  updater_json=""
  addon_slug=""
  current_version=""
  image_name=""
  changelog_updated=0
  updater_updated=0

  if [[ -f "$addon_path/config.json" ]]; then
    config_json=$(cat "$addon_path/config.json")
  fi
  if [[ -f "$addon_path/build.json" ]]; then
    build_json=$(cat "$addon_path/build.json")
  fi
  if [[ -f "$addon_path/updater.json" ]]; then
    updater_json=$(cat "$addon_path/updater.json")
  fi

  # Determine slug
  addon_slug=$(jq -r '.slug // empty' <<< "$config_json")
  if [[ -z "$addon_slug" ]]; then
    addon_slug=$(basename "$addon_path")
  fi

  # Determine current version (prefer updater.json upstream_version then config.json version)
  current_version=$(jq -r '.upstream_version // empty' <<< "$updater_json")
  if [[ -z "$current_version" ]]; then
    current_version=$(jq -r '.version // empty' <<< "$config_json")
  fi
  if [[ -z "$current_version" && -n "$build_json" ]]; then
    current_version=$(jq -r '.version // empty' <<< "$build_json")
  fi
  current_version=${current_version:-"unknown"}

  # Get image name (docker image)
  # Try config.json image or build.json image or updater.json image
  image_name=$(jq -r '.image // empty' <<< "$config_json")
  if [[ -z "$image_name" ]]; then
    image_name=$(jq -r '.image // empty' <<< "$build_json")
  fi
  if [[ -z "$image_name" ]]; then
    image_name=$(jq -r '.image // empty' <<< "$updater_json")
  fi

  # If image is JSON string (multiarch), pick amd64 or aarch64 (amd64 preferred)
  if jq -e . >/dev/null 2>&1 <<< "$image_name"; then
    # parse image JSON map
    image_name=$(jq -r '.amd64 // .aarch64 // first' <<< "$image_name" | tr -d '"')
  fi

  if [[ -z "$image_name" ]]; then
    log "$COLOR_YELLOW" "⚠️ Addon $addon_slug missing image field, skipping."
    continue
  fi

  log "$COLOR_PURPLE" "🧩 Addon: $addon_slug"
  log "$COLOR_YELLOW" "🔢 Current version: $current_version"
  log "$COLOR_YELLOW" "📦 Image: $image_name"

  # Determine latest tag by priority: Docker Hub, LinuxServer.io, GitHub
  # Extract image repo and tag
  local image_repo image_tag
  image_repo="${image_name%%:*}"
  image_tag="${image_name#*:}"
  if [[ "$image_tag" == "$image_repo" ]]; then
    image_tag="latest"
  fi

  # Remove tag for queries
  image_repo_no_tag="${image_repo}"

  # Get latest tag from Docker Hub first
  latest_tag=$(get_latest_dockerhub_tag "$image_repo_no_tag")
  if [[ "$latest_tag" == "latest" ]]; then
    # try LinuxServer.io
    latest_tag=$(get_latest_linuxserver_tag "$image_repo_no_tag")
  fi

  # If still latest, and image is GitHub repo, try GitHub releases
  if [[ "$latest_tag" == "latest" && "$image_repo_no_tag" =~ github.com ]]; then
    # extract owner/repo from url
    repo_path=$(echo "$image_repo_no_tag" | sed -E 's#.*github.com[:/]+([^/]+/[^/]+).*#\1#')
    if [[ -n "$repo_path" ]]; then
      latest_tag=$(get_latest_github_tag "$repo_path")
    fi
  fi

  if [[ -z "$latest_tag" ]]; then
    latest_tag="latest"
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_tag"

  # Compare current_version and latest_tag
  if [[ "$current_version" != "$latest_tag" ]]; then
    log "$COLOR_GREEN" "⬆️  Updating $addon_slug from $current_version to $latest_tag"

    # Update updater.json
    updater_json_path="$addon_path/updater.json"
    dt_now=$(date +"%d-%m-%Y %H:%M")
    # Compose new updater.json content
    updated_json=$(jq -n \
      --arg slug "$addon_slug" \
      --arg img "$image_name" \
      --arg v "$latest_tag" \
      --arg dt "$dt_now" \
      '{slug: $slug, image: $img, upstream_version: $v, last_update: $dt}')
    echo "$updated_json" > "$updater_json_path"
    updater_updated=1
    log "$COLOR_GREEN" "✅ Updated updater.json for $addon_slug"

    # Update or create CHANGELOG.md
    changelog_path="$addon_path/CHANGELOG.md"
    changelog_entry="v$latest_tag ($(date +"%d-%m-%Y"))\n\n    Update to latest version from $image_repo_no_tag (changelog: see upstream repo)"
    if [[ ! -f "$changelog_path" ]]; then
      echo -e "# Changelog for $addon_slug\n\n$changelog_entry" > "$changelog_path"
      changelog_updated=1
      log "$COLOR_GREEN" "🆕 Created CHANGELOG.md for $addon_slug"
    else
      echo -e "\n\n$changelog_entry" >> "$changelog_path"
      changelog_updated=1
      log "$COLOR_GREEN" "✅ Updated CHANGELOG.md for $addon_slug"
    fi

    any_update=1
    notify_messages+=("$addon_slug updated from $current_version to $latest_tag")
  else
    log "$COLOR_GREEN" "✔️ $addon_slug is already up to date ($current_version)"
  fi
  log "$COLOR_RESET" "----------------------------"
done

if (( any_update == 1 )); then
  log "$COLOR_BLUE" "🔄 Committing changes to GitHub..."
  git -C "$REPO_DIR" add .
  git -C "$REPO_DIR" commit -m "chore: update addons versions $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
  if git -C "$REPO_DIR" push origin main; then
    log "$COLOR_GREEN" "✅ Git push successful."
  else
    log "$COLOR_RED" "❌ Git push failed."
  fi

  # Send notifications for updates
  msg="Addon updates:\n"
  for m in "${notify_messages[@]}"; do
    msg+="$m\n"
  done

  log "$COLOR_BLUE" "📢 Sending notifications..."
  send_notification gotify "$msg"
  send_notification mailrise "$msg"
  send_notification apprise "$msg"
else
  log "$COLOR_GREEN" "ℹ️ No updates found, no changes committed."
fi

# Calculate next run time until cron
next_run=$(next_run_time "$CRON_SCHEDULE" "$TIMEZONE")
log "$COLOR_BLUE" "⏳ Next run in: $next_run"

log "$COLOR_BLUE" "😴 Add-on Updater finished."

exit 0
