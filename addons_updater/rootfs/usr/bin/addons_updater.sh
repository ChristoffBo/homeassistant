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

# ===== CLONE OR PULL REPO =====
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

[ "$DRY_RUN" = true ] && log_dryrun "===== ADDON UPDATER STARTED (Dry Run) =====" || log_update "===== ADDON UPDATER STARTED (Live Mode) ====="

# ===== FUNCTIONS =====
get_latest_tag() {
  local image=$1
  local registry="docker"
  case "$image" in
    lscr.io/*) registry="linuxserver";;
  esac

  if [ "$registry" = "linuxserver" ]; then
    local repo_name=${image#lscr.io/}
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/linuxserver/${repo_name}/tags?page_size=100" | jq -r '.results[].name') || return 1
  else
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/${image}/tags?page_size=100" | jq -r '.results[].name') || return 1
  fi

  echo "$tags" | grep -Ev 'latest|rc|dev|test' | sort -Vr | head -n 1
}

send_gotify() {
  local title=$1
  local message=$2
  local priority=${3:-5}
  [ -z "$GOTIFY_URL" ] && return
  curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
    -F "title=$title" \
    -F "message=$message" \
    -F "priority=$priority" >/dev/null || log_warn "Failed to send Gotify notification."
}

# ===== MAIN LOOP =====
NOTES=""
for addon in */config.json; do
  dir=$(dirname "$addon")
  [ "$dir" = ".git" ] && continue

  name=$(jq -r '.name // empty' "$addon")
  image=$(jq -r '.image // empty' "$addon")
  [ -z "$image" ] && image=$(jq -r '.build.image // empty' "$dir/build.json")
  [ -z "$image" ] && continue

  latest=$(get_latest_tag "$image")
  [ -z "$latest" ] && log_warn "$dir: Failed to get latest tag" && continue

  current=$(jq -r '.version // empty' "$addon")
  [ -z "$current" ] && current=$(jq -r '.version // empty' "$dir/build.json")
  [ -z "$current" ] && current=$(jq -r '.version // empty' "$dir/updater.json")
  [ -z "$current" ] && current="unknown"

  if [ "$latest" != "$current" ]; then
    if [ "$DRY_RUN" = true ]; then
      log_dryrun "$dir: Simulated update from $current to $latest"
      NOTES="$NOTES\n🧪 $name: $current → $latest"
    else
      log_update "$dir: Updating from $current to $latest"
      jq --arg ver "$latest" '.version=$ver' "$addon" > tmp && mv tmp "$addon"
      jq --arg ver "$latest" '.version=$ver' "$dir/build.json" > tmp && mv tmp "$dir/build.json"
      jq --arg ver "$latest" '.version=$ver' "$dir/updater.json" > tmp && mv tmp "$dir/updater.json"

      [ ! -f "$dir/CHANGELOG.md" ] && echo "# Changelog" > "$dir/CHANGELOG.md"
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

if [ "$DRY_RUN" != true ]; then
  git push origin "$BRANCH"
fi

[ -n "$GOTIFY_URL" ] && {
  TITLE="Addon Updater Report [$(date '+%Y-%m-%d')]"
  MSG="$(echo -e "$NOTES")"
  send_gotify "$TITLE" "$MSG"
}

log_info "===== ADDON UPDATER FINISHED ====="

# ===== END TIMER =====
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
log_info "Completed in ${ELAPSED}s"
