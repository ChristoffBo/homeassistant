#!/bin/sh
set -e

# Fix HOME if not set (important for git)
export HOME=${HOME:-/root}

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

LOG() {
  # Usage: LOG LEVEL MESSAGE
  level=$1
  shift
  msg=$*
  case $level in
    INFO) color=$GREEN ;;
    WARN) color=$YELLOW ;;
    ERROR) color=$RED ;;
    DRYRUN) color=$MAGENTA ;;
    *) color=$NC ;;
  esac
  echo "${color}[$level]${NC} $msg"
}

# Read options from JSON file
OPTIONS_FILE="/data/options.json"

get_option() {
  # POSIX safe JSON parsing for simple string values
  # usage: get_option key
  key=$1
  grep -o "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$OPTIONS_FILE" 2>/dev/null | head -1 | cut -d'"' -f4
}

# Load options
GIT_USER=$(get_option "gituser")
GIT_EMAIL=$(get_option "gitmail")
GIT_API_TOKEN=$(get_option "gitapi")
REPOSITORY=$(get_option "repository")
VERBOSE=$(get_option "verbose")
DRY_RUN=$(get_option "dry_run")
ENABLE_NOTIFICATIONS=$(get_option "enable_notifications")
GOTIFY_URL=$(get_option "gotify_url")
GOTIFY_TOKEN=$(get_option "gotify_token")
GITEA_API_URL=$(get_option "gitea_api_url")
GITEA_TOKEN=$(get_option "gitea_token")

# Convert true/false strings to lowercase
VERBOSE=$(echo "$VERBOSE" | tr '[:upper:]' '[:lower:]')
DRY_RUN=$(echo "$DRY_RUN" | tr '[:upper:]' '[:lower:]')
ENABLE_NOTIFICATIONS=$(echo "$ENABLE_NOTIFICATIONS" | tr '[:upper:]' '[:lower:]')

[ "$VERBOSE" = "true" ] && LOG INFO "Verbose mode enabled"
[ "$DRY_RUN" = "true" ] && LOG DRYRUN "Dry run mode enabled. No changes will be pushed."

# Setup git repository path
REPO_NAME=$(basename "$REPOSITORY")
CLONE_DIR="/data/$REPO_NAME"

# Notification function
notify() {
  title="$1"
  message="$2"

  if [ "$ENABLE_NOTIFICATIONS" != "true" ]; then
    [ "$VERBOSE" = "true" ] && LOG WARN "Notifications disabled."
    return
  fi

  if [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
    [ "$VERBOSE" = "true" ] && LOG INFO "Sending Gotify notification..."

    # Compose JSON payload safely
    payload=$(printf '{"title":"%s","message":"%s","priority":5}' "$title" "$message")

    curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$payload" >/dev/null 2>&1

    if [ $? -eq 0 ]; then
      [ "$VERBOSE" = "true" ] && LOG INFO "Gotify notification sent successfully."
    else
      LOG ERROR "Failed to send Gotify notification."
    fi
  else
    [ "$VERBOSE" = "true" ] && LOG WARN "Gotify URL or token missing, skipping notification."
  fi
}

# Clone or update git repository
update_repo() {
  if [ ! -d "$CLONE_DIR/.git" ]; then
    LOG INFO "Cloning repository $REPOSITORY..."
    if [ -n "$GIT_USER" ] && [ -n "$GIT_API_TOKEN" ]; then
      # Use token authentication for clone
      GIT_URL="https://$GIT_USER:$GIT_API_TOKEN@github.com/$REPOSITORY.git"
    else
      GIT_URL="https://github.com/$REPOSITORY.git"
    fi
    git clone --depth 1 "$GIT_URL" "$CLONE_DIR" || {
      LOG ERROR "Failed to clone repository."
      exit 1
    }
  else
    LOG INFO "Repository already exists, updating..."
    cd "$CLONE_DIR"
    git fetch origin || {
      LOG ERROR "Failed to fetch updates."
      exit 1
    }
    # Reset to remote branch main (or detect default branch)
    git reset --hard origin/main || {
      LOG ERROR "Failed to reset repository."
      exit 1
    }
  fi
}

# Parse version from addon JSON files (try config.json, then updater.json, then build.json)
get_current_version() {
  addon_dir="$1"
  version=""

  for jsonfile in config.json updater.json build.json; do
    if [ -f "$addon_dir/$jsonfile" ]; then
      version=$(grep -m1 '"version"' "$addon_dir/$jsonfile" | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
      [ -n "$version" ] && break
    fi
  done
  echo "$version"
}

# Compare semantic versions (simple)
version_gt() {
  # returns 0 if $1 > $2 else 1
  # naive lex comparison for demo
  [ "$1" = "$2" ] && return 1
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" != "$1" ]
}

# Process each addon directory inside repo
process_addons() {
  cd "$CLONE_DIR"

  for addon in */; do
    addon=${addon%/}
    LOG INFO "Processing addon $addon..."

    addon_path="$CLONE_DIR/$addon"
    current_version=$(get_current_version "$addon_path")
    if [ -z "$current_version" ]; then
      LOG WARN "$addon: Could not determine current version from config/updater/build.json. Skipping."
      continue
    fi

    # Fake: simulate fetching latest version from registry or GitHub API
    # TODO: Replace this logic with real Docker tag or GitHub release fetch
    latest_version="$current_version" # Placeholder, no update detected

    # For demo, let's pretend there's an update for "gitea" addon only
    if [ "$addon" = "gitea" ]; then
      latest_version="v1.24.3"
    fi

    if version_gt "$latest_version" "$current_version"; then
      LOG INFO "$addon: Update available: $current_version -> $latest_version"

      if [ "$DRY_RUN" = "true" ]; then
        LOG DRYRUN "$addon: Update simulated from $current_version to $latest_version."
      else
        # Update the version in the config/updater/build.json file (here just updater.json)
        updater_file="$addon_path/updater.json"
        if [ -f "$updater_file" ]; then
          # Use sed to replace version string safely
          sed -i -E "s/(\"version\"[[:space:]]*:[[:space:]]*\")[^\"]+\"/\1$latest_version\"/" "$updater_file"
          LOG INFO "$addon: updater.json version updated to $latest_version."
        else
          LOG WARN "$addon: updater.json not found, cannot update version."
        fi

        # Commit changes
        cd "$CLONE_DIR"
        git config user.name "$GIT_USER"
        git config user.email "$GIT_EMAIL"
        git add "$addon/updater.json"
        git commit -m "Update $addon version to $latest_version"
        if [ "$DRY_RUN" != "true" ]; then
          git push origin main
        fi

        # Send notification
        notify "Addon Update" "$addon updated from $current_version to $latest_version"
      fi
    else
      LOG INFO "$addon: You are running the latest version: $current_version"
    fi
  done
}

main() {
  LOG INFO "===== ADDON UPDATER STARTED ====="

  if [ -z "$REPOSITORY" ]; then
    LOG ERROR "No repository configured in options.json"
    exit 1
  fi

  update_repo
  process_addons

  LOG INFO "===== ADDON UPDATER FINISHED ====="
}

main
