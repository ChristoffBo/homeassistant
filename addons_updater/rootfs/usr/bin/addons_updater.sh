#!/bin/sh
set -e

# ===== COLOR SETUP =====
if [ -t 1 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  CYAN='\033[0;36m'
  GRAY='\033[1;30m'
  NC='\033[0m'
else
  RED=''
  GREEN=''
  YELLOW=''
  BLUE=''
  CYAN=''
  GRAY=''
  NC=''
fi

# ===== TIMER =====
START_TIME=$(date +%s)

# ===== ENV =====
TZ=${TZ:-"Africa/Johannesburg"}
export TZ
cd /data || exit 1

# ===== LOGGING FUNCTIONS =====
log_info()   { echo "${BLUE}[INFO]${NC} $1"; }
log_warn()   { echo "${YELLOW}[WARN]${NC} $1"; }
log_error()  { echo "${RED}[ERROR]${NC} $1"; }
log_update() { echo "${GREEN}[UPDATE]${NC} $1"; }
log_dryrun() { echo "${CYAN}[DRYRUN]${NC} $1"; }

# ===== LOAD CONFIG =====
OPTIONS_JSON=/data/options.json
REPO=$(jq -r '.repository // empty' "$OPTIONS_JSON")
BRANCH=$(jq -r '.branch // "main"' "$OPTIONS_JSON")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_JSON")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_JSON")
DRY_RUN=$(jq -r '.dry_run // true' "$OPTIONS_JSON")
NOTIFY_ENABLED=$(jq -r '.enable_notifications // false' "$OPTIONS_JSON")

# Validate repo URL
if [ -z "$REPO" ]; then
  log_error "Git repository URL is empty or missing in options.json! Please fix."
  exit 1
fi

log_info "Using repo: $REPO"
log_info "Using branch: $BRANCH"
[ "$DRY_RUN" = true ] && log_dryrun "Dry run mode: Enabled" || log_update "Dry run mode: Disabled"
[ "$NOTIFY_ENABLED" = true ] && log_info "Gotify notifications: Enabled" || log_warn "Gotify notifications: Disabled"
echo "-----------------------------------------------------------"

# ===== CLONE OR UPDATE REPO =====
if [ ! -d repo ]; then
  log_info "Cloning repository..."
  git clone --depth=1 --branch "$BRANCH" "$REPO" repo
else
  log_info "Repository exists, updating..."
  cd repo || exit 1
  git pull
  cd ..
fi

cd repo || exit 1

git config user.name "AddonUpdater"
git config user.email "addon-updater@local"

# ===== FUNCTION: Get latest tag for Docker Hub and LinuxServer.io =====
get_latest_tag() {
  local image=$1
  local repo_name=""
  local tags=""
  local registry="docker"

  if echo "$image" | grep -q "^lscr.io/"; then
    registry="linuxserver"
    repo_name=$(echo "$image" | cut -d/ -f2-)
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/linuxserver/${repo_name}/tags?page_size=100" 2>/dev/null | jq -r '.results[].name' 2>/dev/null) || return 1
  else
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/${image}/tags?page_size=100" 2>/dev/null | jq -r '.results[].name' 2>/dev/null) || return 1
  fi

  # Filter out unwanted tags like 'latest', 'rc', 'dev', 'test' etc.
  echo "$tags" | grep -Ev 'latest|rc|dev|test' | sort -Vr | head -n 1
}

# ===== FUNCTION: Send Gotify Notification =====
send_gotify() {
  local title=$1
  local message=$2
  local priority=${3:-5}
  if [ -z "$GOTIFY_URL" ] || [ -z "$GOTIFY_TOKEN" ] || [ "$NOTIFY_ENABLED" != true ]; then
    return
  fi

  curl -s -X POST "${GOTIFY_URL}/message?token=${GOTIFY_TOKEN}" \
    -F "title=${title}" \
    -F "message=${message}" \
    -F "priority=${priority}" >/dev/null 2>&1 || log_warn "Failed to send Gotify notification."
}

# ===== MAIN LOOP =====
NOTES=""
for addon_config in */config.json; do
  dir=$(dirname "$addon_config")
  [ "$dir" = ".git" ] && continue

  name=$(jq -r '.name // empty' "$addon_config")
  image=$(jq -r '.image // empty' "$addon_config")

  # If no image in config.json, try build.json
  if [ -z "$image" ]; then
    if [ -f "$dir/build.json" ]; then
      image=$(jq -r '.image // empty' "$dir/build.json")
    fi
  fi

  # Still no image? Skip and warn
  if [ -z "$image" ]; then
    log_warn "$dir: No image found in config.json or build.json, skipping."
    continue
  fi

  # Get current version from config.json, fallback to build.json or updater.json
  current=$(jq -r '.version // empty' "$addon_config")
  if [ -z "$current" ] && [ -f "$dir/build.json" ]; then
    current=$(jq -r '.version // empty' "$dir/build.json")
  fi
  if [ -z "$current" ] && [ -f "$dir/updater.json" ]; then
    current=$(jq -r '.version // empty' "$dir/updater.json")
  fi
  current=${current:-unknown}

  latest=$(get_latest_tag "$image")
  if [ -z "$latest" ]; then
    log_warn "$dir: Failed to get latest tag for image $image"
    continue
  fi

  # Normalize 'latest' and empty tags
  if [ "$latest" = "latest" ] || [ -z "$latest" ]; then
    latest="unknown"
  fi

  # Compare versions and update if needed
  if [ "$latest" != "$current" ] && [ "$latest" != "unknown" ]; then
    if [ "$DRY_RUN" = true ]; then
      log_dryrun "$dir: Simulated update from $current to $latest"
      NOTES="${NOTES}\n🧪 ${name}: ${current} → ${latest} (simulated)"
    else
      log_update "$dir: Updating from $current to $latest"
      # Update version in config.json, build.json, updater.json if they exist
      jq --arg ver "$latest" '.version=$ver' "$addon_config" > tmp && mv tmp "$addon_config"
      if [ -f "$dir/build.json" ]; then
        jq --arg ver "$latest" '.version=$ver' "$dir/build.json" > tmp && mv tmp "$dir/build.json"
      fi
      if [ -f "$dir/updater.json" ]; then
        jq --arg ver "$latest" '.version=$ver' "$dir/updater.json" > tmp && mv tmp "$dir/updater.json"
      fi

      # Update or create CHANGELOG.md
      if [ ! -f "$dir/CHANGELOG.md" ]; then
        echo "# Changelog" > "$dir/CHANGELOG.md"
      fi
      echo -e "\n## $latest - $(date '+%Y-%m-%d')\nUpdated from $current to $latest\nSource: https://hub.docker.com/r/$image/tags" >> "$dir/CHANGELOG.md"

      git add "$dir/"*
      git commit -m "$dir: update from $current to $latest"
      NOTES="${NOTES}\n✅ ${name}: ${current} → ${latest}"
    fi
  else
    log_info "$dir: No update needed, version is $current"
    NOTES="${NOTES}\nℹ️ ${name}: ${current} (up to date)"
  fi
done

# Push changes if not dry run
if [ "$DRY_RUN" != true ]; then
  git push origin "$BRANCH"
fi

# Send notification always (per your request)
if [ "$NOTIFY_ENABLED" = true ]; then
  TITLE="Addon Updater Report [$(date '+%Y-%m-%d')]"
  MSG=$(echo -e "$NOTES")
  send_gotify "$TITLE" "$MSG"
fi

log_info "===== ADDON UPDATER FINISHED ====="

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
log_info "Completed in ${ELAPSED}s"
