#!/bin/sh
set -e

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Log function with color and levels
LOG() {
  level=$1
  shift
  case "$level" in
    INFO) color=$GREEN ;;
    WARN) color=$YELLOW ;;
    ERROR) color=$RED ;;
    DRYRUN) color=$MAGENTA ;;
    *) color=$NC ;;
  esac
  printf "%b[%s]%b %s\n" "$color" "$level" "$NC" "$*"
}

# Load options.json
OPTIONS_FILE="/data/options.json"
if [ ! -f "$OPTIONS_FILE" ]; then
  LOG ERROR "Options file $OPTIONS_FILE not found. Exiting."
  exit 1
fi

# Parse options using jq (must be installed in your container)
DRY_RUN=$(jq -r '.dry_run // "true"' "$OPTIONS_FILE")
GIT_USER=$(jq -r '.gituser // empty' "$OPTIONS_FILE")
GIT_EMAIL=$(jq -r '.gitmail // empty' "$OPTIONS_FILE")
REPOSITORY=$(jq -r '.repository // empty' "$OPTIONS_FILE")
ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications // false' "$OPTIONS_FILE")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_FILE")
GITEA_API_URL=$(jq -r '.gitea_api_url // empty' "$OPTIONS_FILE")
GITEA_TOKEN=$(jq -r '.gitea_token // empty' "$OPTIONS_FILE")

# Basic checks
if [ -z "$REPOSITORY" ]; then
  LOG ERROR "No repository specified in options.json."
  exit 1
fi

# Directory where repo will be cloned
CLONE_DIR="/data/$(basename "$REPOSITORY")"

# Function to send notification (Gotify & Gitea supported)
notify() {
  local title=$1
  local message=$2

  if [ "$ENABLE_NOTIFICATIONS" != "true" ]; then
    LOG INFO "Notifications disabled."
    return 0
  fi

  # Gotify notification
  if [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
    curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":5}" > /dev/null 2>&1 && \
    LOG INFO "Gotify notification sent."
  fi

  # Gitea notification - example: create an issue or comment (simplified)
  if [ -n "$GITEA_API_URL" ] && [ -n "$GITEA_TOKEN" ]; then
    # Here you should customize your Gitea notification API calls accordingly
    # This is a placeholder example:
    curl -s -X POST "$GITEA_API_URL/repos/$REPOSITORY/issues" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\", \"body\":\"$message\"}" > /dev/null 2>&1 && \
    LOG INFO "Gitea notification sent."
  fi
}

# Version comparison function (returns true if $1 > $2)
version_gt() {
  # Use sort -V if available, else fallback to string comparison
  if command -v sort > /dev/null 2>&1; then
    test "$(printf '%s\n%s' "$1" "$2" | sort -V | head -n1)" != "$1"
  else
    [ "$1" != "$2" ] && [ "$1" \> "$2" ]
  fi
}

# Determine current version from a given file
get_version_from_file() {
  local file=$1
  if [ ! -f "$file" ]; then
    echo ""
    return
  fi
  # Try to extract version field from JSON file
  jq -r '.version // empty' "$file" 2>/dev/null || echo ""
}

# Update version in JSON file (config.json, build.json, updater.json)
update_version_in_file() {
  local file=$1
  local new_version=$2

  if [ ! -f "$file" ]; then
    LOG WARN "File $file does not exist, cannot update version."
    return 1
  fi

  # Backup original file
  cp "$file" "$file.bak"

  # Update the version field using jq
  if jq --arg v "$new_version" '.version = $v' "$file.bak" > "$file.tmp"; then
    mv "$file.tmp" "$file"
  else
    LOG ERROR "Failed to update version in $file"
    mv "$file.bak" "$file"
    return 1
  fi

  # Check if file changed
  if cmp -s "$file" "$file.bak"; then
    LOG INFO "$file: version already up to date."
    rm "$file.bak"
    return 2
  else
    LOG INFO "$file: version updated to $new_version."
    rm "$file.bak"
    return 0
  fi
}

# Clone or update repo
prepare_repo() {
  if [ ! -d "$CLONE_DIR/.git" ]; then
    LOG INFO "Cloning repository $REPOSITORY..."
    git clone --depth 1 "https://github.com/$REPOSITORY.git" "$CLONE_DIR"
  else
    LOG INFO "Repository already exists, updating..."
    cd "$CLONE_DIR"
    git fetch origin main
    git reset --hard origin/main
  fi
}

# Main process
process_addons() {
  cd "$CLONE_DIR" || {
    LOG ERROR "Failed to enter repo directory $CLONE_DIR"
    exit 1
  }

  for addon in */; do
    addon=${addon%/}
    LOG INFO "Processing addon $addon..."

    # Detect which JSON file to check/update
    addon_dir="$CLONE_DIR/$addon"
    config_json="$addon_dir/config.json"
    build_json="$addon_dir/build.json"
    updater_json="$addon_dir/updater.json"

    current_version=""
    version_file=""

    # Check for version in config.json
    current_version=$(get_version_from_file "$config_json")
    if [ -n "$current_version" ]; then
      version_file="$config_json"
    else
      # fallback to build.json
      current_version=$(get_version_from_file "$build_json")
      if [ -n "$current_version" ]; then
        version_file="$build_json"
      else
        # fallback to updater.json
        current_version=$(get_version_from_file "$updater_json")
        if [ -n "$current_version" ]; then
          version_file="$updater_json"
        else
          LOG WARN "$addon: No version found in config.json, build.json or updater.json. Skipping."
          continue
        fi
      fi
    fi

    # Simulate fetching latest version for demonstration:
    # In your real script replace this logic with API calls or tag fetch from DockerHub/GHCR/LinuxServer.io
    latest_version="$current_version"
    if [ "$addon" = "gitea" ]; then
      latest_version="v1.24.3"
    fi

    if version_gt "$latest_version" "$current_version"; then
      LOG INFO "$addon: Update available: $current_version -> $latest_version"

      if [ "$DRY_RUN" = "true" ]; then
        LOG DRYRUN "$addon: Update simulated from $current_version to $latest_version."
      else
        # Update the version in the correct JSON file
        update_version_in_file "$version_file" "$latest_version"
        ret=$?

        if [ $ret -eq 0 ]; then
          # Commit and push changes
          git config user.name "$GIT_USER"
          git config user.email "$GIT_EMAIL"
          git add "$addon"

          if git diff --cached --quiet; then
            LOG INFO "$addon: No changes to commit."
          else
            git commit -m "Update $addon version to $latest_version"
            git push origin main
            LOG INFO "$addon: Changes pushed to remote."

            # Send notifications
            notify "Addon Update" "$addon updated from $current_version to $latest_version"
          fi
        elif [ $ret -eq 2 ]; then
          LOG INFO "$addon: Version file already up to date, no changes."
        else
          LOG WARN "$addon: Failed to update version."
        fi
      fi
    else
      LOG INFO "$addon: You are running the latest version: $current_version"
    fi
  done
}

main() {
  LOG INFO "===== ADDON UPDATER STARTED ====="
  if [ "$DRY_RUN" = "true" ]; then
    LOG DRYRUN "Dry run mode enabled. No changes will be pushed."
  else
    LOG INFO "Live mode enabled. Changes will be pushed."
  fi

  prepare_repo
  process_addons

  LOG INFO "===== ADDON UPDATER FINISHED ====="
}

main
