#!/bin/sh
set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

LOG() {
  level=$1
  shift
  case "$level" in
    INFO) color=$GREEN ;;
    WARN) color=$YELLOW ;;
    ERROR) color=$RED ;;
    DRYRUN) color=$MAGENTA ;;
    LIVE) color=$CYAN ;;
    *) color=$NC ;;
  esac
  printf "%b[%s]%b %s\n" "$color" "$level" "$NC" "$*"
}

OPTIONS_FILE="/data/options.json"

# Check jq presence
if ! command -v jq >/dev/null 2>&1; then
  LOG ERROR "jq is required but not installed."
  exit 1
fi

# Load options
DRY_RUN=$(jq -r '.dry_run // "true"' "$OPTIONS_FILE")
GIT_USER=$(jq -r '.gituser // empty' "$OPTIONS_FILE")
GIT_EMAIL=$(jq -r '.gitmail // empty' "$OPTIONS_FILE")
REPOSITORY=$(jq -r '.repository // empty' "$OPTIONS_FILE")
GIT_PROVIDER=$(jq -r '.git_provider // "github"' "$OPTIONS_FILE" | tr '[:upper:]' '[:lower:]')
ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications // false' "$OPTIONS_FILE")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_FILE")

if [ -z "$REPOSITORY" ]; then
  LOG ERROR "No repository specified in options.json."
  exit 1
fi

CLONE_DIR="/data/$(basename "$REPOSITORY")"

if [ "$GIT_PROVIDER" = "gitea" ]; then
  GIT_CLONE_URL="https://gitea.example.com/$REPOSITORY.git"
else
  GIT_CLONE_URL="https://github.com/$REPOSITORY.git"
fi

notify() {
  local title=$1
  local message=$2

  if [ "$ENABLE_NOTIFICATIONS" != "true" ]; then
    LOG INFO "Notifications disabled."
    return 0
  fi

  if [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\", \"message\":\"$message\", \"priority\":5}")

    if [ "$http_code" -eq 200 ]; then
      LOG INFO "Gotify notification sent."
    else
      LOG WARN "Failed to send Gotify notification. HTTP status: $http_code"
    fi
  else
    LOG WARN "Gotify URL or token missing, skipping notification."
  fi
}

version_gt() {
  v1=$1
  v2=$2

  # Treat 'latest' as lowest version
  [ "$v1" = "latest" ] && return 1
  [ "$v2" = "latest" ] && return 0

  highest=$(printf '%s\n%s\n' "$v1" "$v2" | sort -V | tail -n1)
  [ "$highest" = "$v1" ] && [ "$v1" != "$v2" ]
}

fetch_latest_tag() {
  local image=$1
  # Placeholder for actual tag fetching logic, update this for real API calls
  case "$image" in
    gitea/gitea) echo "1.24.3" ;;
    linuxserver/heimdall) echo "2.4.0" ;;
    linuxserver/metube) echo "1.5.2" ;;
    linuxserver/gotify) echo "2.6.3" ;;
    *) echo "latest" ;;
  esac
}

get_version_from_file() {
  local file=$1
  if [ ! -f "$file" ]; then
    echo ""
    return
  fi
  jq -r '.version // empty' "$file" 2>/dev/null || echo ""
}

update_version_in_file() {
  local file=$1
  local new_version=$2

  if [ ! -f "$file" ]; then
    LOG WARN "File $file does not exist."
    return 1
  fi

  cp "$file" "$file.bak"

  if jq --arg v "$new_version" '.version = $v' "$file.bak" > "$file.tmp"; then
    mv "$file.tmp" "$file"
  else
    LOG ERROR "Failed updating version in $file"
    mv "$file.bak" "$file"
    return 1
  fi

  if cmp -s "$file" "$file.bak"; then
    rm "$file.bak"
    return 2 # no change
  else
    rm "$file.bak"
    LOG INFO "$file updated to version $new_version"
    return 0
  fi
}

prepare_repo() {
  if [ ! -d "$CLONE_DIR/.git" ]; then
    LOG INFO "Cloning repository $REPOSITORY..."
    git clone --depth 1 "$GIT_CLONE_URL" "$CLONE_DIR"
  else
    LOG INFO "Repository exists, updating..."
    cd "$CLONE_DIR"
    git fetch origin main
    git reset --hard origin/main
  fi
}

process_addons() {
  cd "$CLONE_DIR" || {
    LOG ERROR "Cannot enter directory $CLONE_DIR"
    exit 1
  }

  MESSAGE_BODY="Addon Update Summary:\n\n"
  
  for addon in */; do
    addon=${addon%/}
    LOG INFO "Processing addon $addon..."

    addon_dir="$CLONE_DIR/$addon"
    config_json="$addon_dir/config.json"
    build_json="$addon_dir/build.json"
    updater_json="$addon_dir/updater.json"

    current_version=""
    version_file=""

    current_version=$(get_version_from_file "$config_json")
    if [ -n "$current_version" ]; then
      version_file="$config_json"
    else
      current_version=$(get_version_from_file "$build_json")
      if [ -n "$current_version" ]; then
        version_file="$build_json"
      else
        current_version=$(get_version_from_file "$updater_json")
        if [ -n "$current_version" ]; then
          version_file="$updater_json"
        else
          LOG WARN "$addon: No version found, skipping."
          MESSAGE_BODY="${MESSAGE_BODY}${addon}: No version found, skipped.\n"
          continue
        fi
      fi
    fi

    image=""
    case "$addon" in
      gitea) image="gitea/gitea" ;;
      gotify) image="linuxserver/gotify" ;;
      heimdall) image="linuxserver/heimdall" ;;
      metube) image="linuxserver/metube" ;;
      *) image="library/$addon" ;;
    esac

    latest_version=$(fetch_latest_tag "$image")

    # If latest is 'latest' fallback to current_version or 'unknown'
    display_latest_version="$latest_version"
    if [ "$latest_version" = "latest" ] || [ -z "$latest_version" ]; then
      if [ -n "$current_version" ]; then
        display_latest_version="$current_version"
      else
        display_latest_version="unknown"
      fi
    fi

    # Fix current_version display fallback
    if [ -z "$current_version" ]; then
      current_version="unknown"
    fi

    if version_gt "$latest_version" "$current_version"; then
      LOG INFO "$addon: Update available: $current_version -> $display_latest_version"
      if [ "$DRY_RUN" = "true" ]; then
        LOG DRYRUN "$addon: Update simulated from $current_version to $display_latest_version"
        MESSAGE_BODY="${MESSAGE_BODY}${addon}: Update simulated from $current_version to $display_latest_version\n"
      else
        update_version_in_file "$version_file" "$latest_version"
        ret=$?
        if [ $ret -eq 0 ]; then
          git config user.name "$GIT_USER"
          git config user.email "$GIT_EMAIL"
          git add "$addon"

          if git diff --cached --quiet; then
            LOG INFO "$addon: No changes to commit."
            MESSAGE_BODY="${MESSAGE_BODY}${addon}: No changes to commit.\n"
          else
            git commit -m "Update $addon version to $latest_version"
            git push origin main
            LOG INFO "$addon: Changes pushed to remote."
            MESSAGE_BODY="${MESSAGE_BODY}${addon}: Updated from $current_version to $display_latest_version\n"
          fi
        elif [ $ret -eq 2 ]; then
          LOG INFO "$addon: Version file already up to date."
          MESSAGE_BODY="${MESSAGE_BODY}${addon}: Version file already up to date ($display_latest_version)\n"
        else
          LOG WARN "$addon: Failed to update version."
          MESSAGE_BODY="${MESSAGE_BODY}${addon}: Failed to update version.\n"
        fi
      fi
    else
      LOG INFO "$addon: You are running the latest version: $display_latest_version"
      MESSAGE_BODY="${MESSAGE_BODY}${addon}: You are running the latest version: $display_latest_version\n"
    fi
  done

  if [ "$DRY_RUN" = "true" ]; then
    MODE_MSG="[DRYRUN] Mode: Dry Run (no changes pushed)"
  else
    MODE_MSG="[LIVE] Mode: Live (changes pushed)"
  fi

  notify "Addon Updater Result" "$MODE_MSG\n\n$MESSAGE_BODY"
}

main() {
  LOG INFO "===== ADDON UPDATER STARTED ====="
  if [ "$DRY_RUN" = "true" ]; then
    LOG DRYRUN "Dry run mode enabled. No changes will be pushed."
  else
    LOG LIVE "Live mode enabled. Changes will be pushed."
  fi

  prepare_repo
  process_addons

  LOG INFO "===== ADDON UPDATER FINISHED ====="
}

main
