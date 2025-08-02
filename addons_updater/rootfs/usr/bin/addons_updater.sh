#!/bin/sh
set -e

# ------------------------------
# Addons Updater Enhanced
# Automatically update addons with notifications support
# ------------------------------

# Colors for logging (avoid purple)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Dry run and live colors
DRYRUN_COLOR="${YELLOW}"
LIVE_COLOR="${GREEN}"

# Logging functions
log_info() {
  printf "${LIVE_COLOR}[INFO]${NC} %s\n" "$1"
}
log_warn() {
  printf "${RED}[WARN]${NC} %s\n" "$1"
}
log_dryrun() {
  printf "${DRYRUN_COLOR}[DRYRUN]${NC} %s\n" "$1"
}

# Version comparison (returns true if $1 > $2)
ver_gt() {
  [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" != "$1" ]
}

# Read config options
CONFIG_FILE="/data/options.json"
if [ ! -f "$CONFIG_FILE" ]; then
  log_warn "options.json not found!"
  exit 1
fi

# Load JSON config
GIT_USER=$(jq -r '.gituser // empty' "$CONFIG_FILE")
GIT_MAIL=$(jq -r '.gitmail // empty' "$CONFIG_FILE")
GIT_API_TOKEN=$(jq -r '.gitapi // empty' "$CONFIG_FILE")
REPOSITORY=$(jq -r '.repository // empty' "$CONFIG_FILE")
VERBOSE=$(jq -r '.verbose // false' "$CONFIG_FILE")
DRY_RUN=$(jq -r '.dry_run // true' "$CONFIG_FILE")
ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications // false' "$CONFIG_FILE")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$CONFIG_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$CONFIG_FILE")
USE_GITEA=$(jq -r '.use_gitea // false' "$CONFIG_FILE")
GITEA_API_URL=$(jq -r '.gitea_api_url // empty' "$CONFIG_FILE")
GITEA_TOKEN=$(jq -r '.gitea_token // empty' "$CONFIG_FILE")

REPO_PATH="/data/$(basename "$REPOSITORY")"

# Print header info
printf "\n-----------------------------------------------------------\n"
printf " Add-on: Addons Updater Enhanced\n Automatically update addons with notifications support\n"
printf "-----------------------------------------------------------\n"
printf " Add-on version: 10.1.1\n"
printf " System: Home Assistant OS (amd64 / qemux86-64)\n"
printf " Repository: %s\n" "$REPOSITORY"
printf " Dry run mode: %s\n" "$( [ "$DRY_RUN" = "true" ] && echo "Enabled" || echo "Disabled" )"
printf " Notifications: %s\n" "$( [ "$ENABLE_NOTIFICATIONS" = "true" ] && echo "Enabled" || echo "Disabled" )"
printf "-----------------------------------------------------------\n\n"

# Setup Git config
export HOME=/tmp
git config --global user.name "$GIT_USER"
git config --global user.email "$GIT_MAIL"

if [ ! -d "$REPO_PATH/.git" ]; then
  log_info "Cloning repository $REPOSITORY..."
  if ! git clone --depth=1 "https://$GIT_API_TOKEN@github.com/$REPOSITORY.git" "$REPO_PATH"; then
    log_warn "Failed to clone repository!"
    exit 1
  fi
else
  log_info "Repository exists, updating..."
  cd "$REPO_PATH"
  git fetch origin main
  git reset --hard origin/main
fi

CHANGELOG=""
UPDATES_OCCURRED=false

# Update version in JSON file helper
update_json_version() {
  local addon_dir=$1
  local version=$2
  local file=$3

  local json_file="$REPO_PATH/$addon_dir/$file"
  if [ -f "$json_file" ]; then
    jq --arg v "$version" '.version=$v' "$json_file" > "${json_file}.tmp" && mv "${json_file}.tmp" "$json_file"
    log_info "$addon_dir: $file version updated to $version."
    CHANGELOG="${CHANGELOG}\n$addon_dir: Version updated to $version"
  else
    log_warn "$addon_dir: $file not found, skipping update."
  fi
}

# Get current addon version by checking config.json, build.json, updater.json (priority order)
get_current_version() {
  local addon_dir=$1
  for file in config.json build.json updater.json; do
    local jf="$REPO_PATH/$addon_dir/$file"
    if [ -f "$jf" ]; then
      local ver
      ver=$(jq -r '.version // empty' "$jf")
      if [ -n "$ver" ] && [ "$ver" != "null" ]; then
        echo "$ver"
        return
      fi
    fi
  done
  echo "unknown"
}

# Fetch latest version depending on source (GitHub or Gitea) or DockerHub fallback
get_latest_version() {
  local addon=$1

  if [ "$USE_GITEA" = "true" ]; then
    # Gitea API version fetching
    # Example call: curl -s -H "Authorization: token $GITEA_TOKEN" "$GITEA_API_URL/repos/youruser/$addon/releases/latest"
    latest=$(curl -s -H "Authorization: token $GITEA_TOKEN" "$GITEA_API_URL/repos/$GIT_USER/$addon/releases/latest" | jq -r '.tag_name // empty')
  else
    # GitHub API version fetching
    latest=$(curl -s -H "Authorization: token $GIT_API_TOKEN" "https://api.github.com/repos/$GIT_USER/$addon/releases/latest" | jq -r '.tag_name // empty')
  fi

  # If no tag_name found, fallback to DockerHub or default 'latest'
  if [ -z "$latest" ]; then
    # Here you could implement DockerHub tag fetch fallback if needed
    latest="latest"
  fi

  # Strip any leading 'v' to standardize version format
  latest="${latest#v}"
  echo "$latest"
}

# Iterate addons excluding .git folder
for addon_dir in $(find "$REPO_PATH" -mindepth 1 -maxdepth 1 -type d ! -name ".git" | xargs -n1 basename); do

  current_version=$(get_current_version "$addon_dir")
  latest_version=$(get_latest_version "$addon_dir")

  if [ "$latest_version" = "latest" ] || [ -z "$latest_version" ]; then
    latest_version="$current_version"
  fi

  if ver_gt "$latest_version" "$current_version"; then
    log_info "$addon_dir: Update available: $current_version -> $latest_version"
    if [ "$DRY_RUN" = "true" ]; then
      log_dryrun "$addon_dir: Update simulated from $current_version to $latest_version"
    else
      # Update all JSON version files if present
      update_json_version "$addon_dir" "$latest_version" "config.json"
      update_json_version "$addon_dir" "$latest_version" "build.json"
      update_json_version "$addon_dir" "$latest_version" "updater.json"

      cd "$REPO_PATH"
      git add .
      git commit -m "Update $addon_dir version to $latest_version"
      git push origin main

      log_info "$addon_dir: Updated to $latest_version and pushed."
    fi
    CHANGELOG="${CHANGELOG}${addon_dir}: Updated from $current_version to $latest_version\n"
    UPDATES_OCCURRED=true
  else
    log_info "$addon_dir: You are running the latest version: $current_version"
    CHANGELOG="${CHANGELOG}${addon_dir}: Already at latest version: $current_version\n"
  fi
done

# Prepare notification message
NOTIFY_MSG="Addons Updater Report:\n\n$CHANGELOG"

if [ "$ENABLE_NOTIFICATIONS" = "true" ]; then
  TITLE="Addon Updater - $( [ "$DRY_RUN" = "true" ] && echo "Dry Run" || echo "Live Run" )"
  # Green for live run, Orange for dry run
  COLOR=$( [ "$DRY_RUN" = "true" ] && echo "#FFA500" || echo "#008000")

  # Prepare Gotify message with colored lines for updated addons
  # Highlight updated lines in green
  GOTIFY_MSG=""
  while IFS= read -r line; do
    if echo "$line" | grep -q "Updated from"; then
      # Green color for updates
      GOTIFY_MSG="${GOTIFY_MSG}<font color=\"green\">${line}</font><br>"
    else
      GOTIFY_MSG="${GOTIFY_MSG}${line}<br>"
    fi
  done <<EOF
$(echo "$NOTIFY_MSG" | sed 's/^/ /')
EOF

  # Build JSON payload for Gotify
  PAYLOAD="{\"title\":\"$TITLE\",\"message\":\"$GOTIFY_MSG\",\"priority\":5,\"extras\":{\"notification\":{\"color\":\"$COLOR\"}}}"

  GOTIFY_ENDPOINT="$GOTIFY_URL/message?token=$GOTIFY_TOKEN"

  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "$GOTIFY_ENDPOINT")

  if [ "$HTTP_STATUS" = "200" ]; then
    log_info "Gotify notification sent."
  else
    log_warn "Failed to send Gotify notification. HTTP status: $HTTP_STATUS"
  fi
fi

log_info "===== ADDON UPDATER FINISHED ====="
