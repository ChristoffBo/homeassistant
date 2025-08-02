#!/bin/sh
set -e

# ===== COLOR DEFINITIONS =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
GRAY='\033[1;30m'
NC='\033[0m'

# ===== START TIMER =====
START_TIME=$(date +%s)

# ===== ENV SETUP =====
TZ=${TZ:-"Africa/Johannesburg"}
export TZ
cd /data || exit 1

# ===== LOGGING UTILS =====
log_info()   { echo "${BLUE}[INFO]${NC} $1"; }
log_warn()   { echo "${YELLOW}[WARN]${NC} $1"; }
log_error()  { echo "${RED}[ERROR]${NC} $1"; }
log_update() { echo "${GREEN}[UPDATE]${NC} $1"; }
log_dryrun() { echo "${CYAN}[DRYRUN]${NC} $1"; }

# ===== LOAD CONFIGURATION =====
OPTIONS_JSON=/data/options.json
REPO=$(jq -r '.repo // empty' "$OPTIONS_JSON")
if [ -z "$REPO" ]; then
  REPO=$(jq -r '.repository // empty' "$OPTIONS_JSON")
fi
BRANCH=$(jq -r '.branch // "main"' "$OPTIONS_JSON")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_JSON")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_JSON")
DRY_RUN=$(jq -r '.dry_run // true' "$OPTIONS_JSON")
ENABLE_NOTIF=$(jq -r '.enable_notifications // false' "$OPTIONS_JSON")
GIT_USER=$(jq -r '.gituser // "AddonUpdater"' "$OPTIONS_JSON")
GIT_MAIL=$(jq -r '.gitmail // "addon-updater@local"' "$OPTIONS_JSON")

# ===== CHECK CONFIG =====
if [ -z "$REPO" ]; then
  log_error "Git repository URL is empty or missing in options.json! Please fix."
  exit 1
fi

log_info "Using repo: $REPO"
log_info "Using branch: $BRANCH"
if [ "$DRY_RUN" = true ]; then
  log_dryrun "Dry run mode: Enabled"
else
  log_update "Dry run mode: Disabled (Live)"
fi
if [ "$ENABLE_NOTIF" = true ]; then
  log_info "Gotify notifications: Enabled"
else
  log_info "Gotify notifications: Disabled"
fi
echo "-----------------------------------------------------------"

# ===== CLONE OR PULL REPO =====
if [ ! -d repo ]; then
  log_info "Cloning repository..."
  git clone --depth=1 --branch "$BRANCH" "$REPO" repo
else
  log_info "Repository exists, updating..."
  cd repo || exit 1
  git pull origin "$BRANCH"
  cd ..
fi

cd repo || exit 1

git config user.name "$GIT_USER"
git config user.email "$GIT_MAIL"

# ===== FUNCTIONS =====

# Get latest tag from Docker Hub or LinuxServer.io
get_latest_tag() {
  local image=$1
  local repo_name
  local tags

  if echo "$image" | grep -q '^lscr.io/'; then
    # LinuxServer.io images
    repo_name=${image#lscr.io/}
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/linuxserver/${repo_name}/tags?page_size=100" | jq -r '.results[].name') || return 1
  else
    # Docker Hub images
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/${image}/tags?page_size=100" | jq -r '.results[].name') || return 1
  fi

  # Filter out unwanted tags and sort semver descending
  echo "$tags" | grep -Ev 'latest|rc|dev|test' | sort -Vr | head -n 1
}

# Send notification to Gotify
send_gotify() {
  local title=$1
  local message=$2
  local priority=${3:-5}

  if [ "$ENABLE_NOTIF" != true ]; then
    return
  fi

  if [ -z "$GOTIFY_URL" ] || [ -z "$GOTIFY_TOKEN" ]; then
    log_warn "Gotify URL or Token missing; skipping notification."
    return
  fi

  response=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
    -F "title=$title" \
    -F "message=$message" \
    -F "priority=$priority")

  if [ "$response" -ne 200 ]; then
    log_warn "Failed to send Gotify notification. HTTP status: $response"
  else
    log_info "Gotify notification sent."
  fi
}

# Update version in config/build/updater.json and changelog
update_version_files() {
  local dir=$1
  local latest=$2
  local current=$3
  local image=$4
  local changelog_path="$dir/CHANGELOG.md"

  # Update JSON files if they exist
  for file in config.json build.json updater.json; do
    local file_path="$dir/$file"
    if [ -f "$file_path" ]; then
      jq --arg ver "$latest" '.version=$ver' "$file_path" > "$file_path.tmp" && mv "$file_path.tmp" "$file_path"
    fi
  done

  # Create changelog if missing
  if [ ! -f "$changelog_path" ]; then
    echo "# Changelog" > "$changelog_path"
  fi

  # Append changelog entry
  echo -e "\n## $latest - $(date '+%Y-%m-%d')\nUpdated from $current to $latest\nSource: https://hub.docker.com/r/$image/tags" >> "$changelog_path"
}

# ===== MAIN LOOP =====

NOTES=""
UPDATED=0

for addon_config in */config.json; do
  dir=$(dirname "$addon_config")
  [ "$dir" = ".git" ] && continue

  name=$(jq -r '.name // empty' "$addon_config")
  image=$(jq -r '.image // empty' "$addon_config")

  # fallback to build.json image
  if [ -z "$image" ] && [ -f "$dir/build.json" ]; then
    image=$(jq -r '.image // empty' "$dir/build.json")
  fi

  if [ -z "$image" ]; then
    log_warn "$dir: No image found in config.json or build.json, skipping."
    continue
  fi

  latest=$(get_latest_tag "$image") || {
    log_warn "$dir: Failed to fetch latest tag for image $image"
    continue
  }

  # Get current version from config, build, or updater.json
  current=$(jq -r '.version // empty' "$addon_config")
  if [ -z "$current" ] && [ -f "$dir/build.json" ]; then
    current=$(jq -r '.version // empty' "$dir/build.json")
  fi
  if [ -z "$current" ] && [ -f "$dir/updater.json" ]; then
    current=$(jq -r '.version // empty' "$dir/updater.json")
  fi
  if [ -z "$current" ]; then
    current="unknown"
  fi

  # Normalize tags (remove leading v or arch prefixes)
  clean_latest=$(echo "$latest" | sed -E 's/^v//')
  clean_current=$(echo "$current" | sed -E 's/^v//')

  # If latest is 'latest' string or empty, skip update and mark as up to date with current version
  if echo "$clean_latest" | grep -qEi 'latest|^$'; then
    clean_latest=$clean_current
  fi

  if [ "$clean_latest" != "$clean_current" ]; then
    if [ "$DRY_RUN" = true ]; then
      log_dryrun "$dir: Simulated update from $clean_current to $clean_latest"
      NOTES="$NOTES\n🧪 $name: $clean_current → $clean_latest"
    else
      log_update "$dir: Updating from $clean_current to $clean_latest"
      update_version_files "$dir" "$clean_latest" "$clean_current" "$image"

      git add "$dir/"*
      git commit -m "$dir: update from $clean_current to $clean_latest"
      UPDATED=1
      NOTES="$NOTES\n✅ $name: $clean_current → $clean_latest"
    fi
  else
    log_info "$dir: No update needed, version is $clean_current"
    NOTES="$NOTES\nℹ️ $name: $clean_current (up to date)"
  fi
done

if [ "$DRY_RUN" != true ] && [ "$UPDATED" -eq 1 ]; then
  git push origin "$BRANCH"
fi

# Send notification with all notes, always send regardless of updates
if [ "$ENABLE_NOTIF" = true ]; then
  TITLE="Addon Updater Report [$(date '+%Y-%m-%d')]"
  MESSAGE="Dry run mode: $DRY_RUN\n\n$(echo -e "$NOTES")"
  send_gotify "$TITLE" "$MESSAGE"
fi

log_info "===== ADDON UPDATER FINISHED ====="

# ===== END TIMER =====
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
log_info "Completed in ${ELAPSED}s"
