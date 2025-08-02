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
BRANCH=$(jq -r '.branch // "main"' "$OPTIONS_JSON")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_JSON")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_JSON")
DRY_RUN=$(jq -r '.dry_run // true' "$OPTIONS_JSON")
NOTIFICATIONS_ENABLED=$(jq -r '.notifications_enabled // true' "$OPTIONS_JSON")

# ===== PREPARE REPO =====
if [ ! -d repo ]; then
  git clone --depth=1 --branch "$BRANCH" "$REPO" repo
else
  cd repo || exit 1
  git pull
  cd ..
fi
cd repo || exit 1

git config user.name "AddonUpdater"
git config user.email "addon-updater@local"

# ===== MODE LOGGING =====
if [ "$DRY_RUN" = true ]; then
  log_dryrun "===== ADDON UPDATER STARTED (Dry Run Mode) ====="
else
  log_update "===== ADDON UPDATER STARTED (Live Mode) ====="
fi

# ===== FUNCTIONS =====
get_latest_tag() {
  local image=$1

  # Fetch tags from Docker Hub repo
  tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/${image}/tags?page_size=100" | jq -r '.results[].name') || return 1

  # Filter out unwanted tags and sort descending semantic versions
  echo "$tags" | grep -Ev 'latest|rc|dev|test' | sort -Vr | head -n 1
}

sanitize_version() {
  # Remove arch prefixes like amd64-, armhf-, etc.
  echo "$1" | sed -E 's/^(amd64-|armhf-|armv7-|aarch64-|i386-)//'
}

send_gotify() {
  local title=$1
  local message=$2
  local priority=${3:-5}
  [ -z "$GOTIFY_URL" ] && return

  curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
    -F "title=$title" \
    -F "message=$message" \
    -F "priority=$priority" >/dev/null 2>&1 || log_warn "Failed to send Gotify notification."
}

# ===== MAIN LOOP =====
NOTES=""
for addon_config in */config.json; do
  dir=$(dirname "$addon_config")
  [ "$dir" = ".git" ] && continue

  name=$(jq -r '.name // empty' "$addon_config")
  image=$(jq -r '.image // empty' "$addon_config")
  # fallback to build.json image if config.json image missing
  if [ -z "$image" ]; then
    image=$(jq -r '.build.image // empty' "$dir/build.json")
  fi
  [ -z "$image" ] && log_warn "$dir: No image specified, skipping." && continue

  latest_tag=$(get_latest_tag "$image")
  if [ -z "$latest_tag" ]; then
    log_warn "$dir: Could not fetch latest tag for $image"
    continue
  fi

  # Sanitize latest and current version for comparison
  latest=$(sanitize_version "$latest_tag")

  current=$(jq -r '.version // empty' "$addon_config")
  [ -z "$current" ] && current=$(jq -r '.version // empty' "$dir/build.json")
  [ -z "$current" ] && current=$(jq -r '.version // empty' "$dir/updater.json")
  [ -z "$current" ] && current="unknown"

  current_sanitized=$(sanitize_version "$current")

  if [ "$latest" != "$current_sanitized" ]; then
    if [ "$DRY_RUN" = true ]; then
      log_dryrun "$dir: Simulated update from $current to $latest"
      NOTES="$NOTES\n🧪 $name: $current → $latest"
    else
      log_update "$dir: Updating from $current to $latest"

      # Update version in config.json or build.json or updater.json as available
      if [ -f "$addon_config" ]; then
        jq --arg ver "$latest" '.version=$ver' "$addon_config" > "$addon_config.tmp" && mv "$addon_config.tmp" "$addon_config"
      fi
      if [ -f "$dir/build.json" ]; then
        jq --arg ver "$latest" '.version=$ver' "$dir/build.json" > "$dir/build.json.tmp" && mv "$dir/build.json.tmp" "$dir/build.json"
      fi
      if [ -f "$dir/updater.json" ]; then
        jq --arg ver "$latest" '.version=$ver' "$dir/updater.json" > "$dir/updater.json.tmp" && mv "$dir/updater.json.tmp" "$dir/updater.json"
      fi

      # Create or append changelog
      if [ ! -f "$dir/CHANGELOG.md" ]; then
        echo "# Changelog" > "$dir/CHANGELOG.md"
      fi
      echo -e "\n## $latest - $(date '+%Y-%m-%d')\nUpdated from $current to $latest\nSource: https://hub.docker.com/r/$image/tags" >> "$dir/CHANGELOG.md"

      git add "$dir/"*
      git commit -m "$dir: update from $current to $latest"

      NOTES="$NOTES\n✅ $name: $current → $latest"
    fi
  else
    log_info "$dir: No update needed, version is $current"
    NOTES="$NOTES\nℹ️ $name: $current (up to date)"
  fi
done

# Push changes if not dry run
if [ "$DRY_RUN" != true ]; then
  git push origin "$BRANCH"
fi

# Prepare notification message with colors for Gotify
prepare_gotify_message() {
  local raw_notes="$1"
  local msg=""

  while IFS= read -r line; do
    # Green color for update lines (✅), default for info (ℹ️), cyan for dry run (🧪)
    if echo "$line" | grep -q "✅"; then
      # Gotify markdown green for updates
      msg="${msg}<b><font color='green'>${line}</font></b><br>"
    elif echo "$line" | grep -q "🧪"; then
      msg="${msg}<b><font color='cyan'>${line}</font></b><br>"
    else
      msg="${msg}${line}<br>"
    fi
  done <<EOF
$raw_notes
EOF

  echo "$msg"
}

# Send notification if enabled
if [ "$NOTIFICATIONS_ENABLED" = true ]; then
  TITLE="Addon Updater Report [$(date '+%Y-%m-%d')]"
  MESSAGE=$(prepare_gotify_message "$NOTES")
  send_gotify "$TITLE" "$MESSAGE"
fi

log_info "===== ADDON UPDATER FINISHED ====="

# ===== END TIMER =====
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
log_info "Completed in ${ELAPSED}s"
