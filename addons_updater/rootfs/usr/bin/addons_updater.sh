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
cd /data || { echo "${RED}Failed to cd /data${NC}"; exit 1; }

# ===== LOGGING UTILS =====
log_info()   { echo "${BLUE}[INFO]${NC} $1"; }
log_warn()   { echo "${YELLOW}[WARN]${NC} $1"; }
log_error()  { echo "${RED}[ERROR]${NC} $1"; }
log_update() { echo "${GREEN}[UPDATE]${NC} $1"; }
log_dryrun() { echo "${CYAN}[DRYRUN]${NC} $1"; }

# ===== LOAD CONFIGURATION =====
OPTIONS_JSON=/data/options.json
REPO=$(jq -r '.repo // empty' "$OPTIONS_JSON" 2>/dev/null || echo "")
BRANCH=$(jq -r '.branch // "main"' "$OPTIONS_JSON" 2>/dev/null || echo "main")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_JSON" 2>/dev/null || echo "")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_JSON" 2>/dev/null || echo "")
DRY_RUN=$(jq -r '.dry_run // true' "$OPTIONS_JSON" 2>/dev/null || echo "true")

# DEBUG PARSED VALUES
echo "Using repo: '$REPO'"
echo "Using branch: '$BRANCH'"
echo "Dry run mode: $DRY_RUN"
echo "Gotify notifications: $( [ -n "$GOTIFY_URL" ] && echo Enabled || echo Disabled )"

if [ -z "$REPO" ]; then
  log_error "Git repository URL is empty or missing in options.json! Please fix."
  exit 1
fi

# ===== CLONE OR UPDATE REPO =====
if [ ! -d repo ]; then
  log_info "Cloning repository..."
  git clone --depth=1 --branch "$BRANCH" "$REPO" repo || {
    log_error "Failed to clone repo $REPO"
    exit 1
  }
else
  log_info "Repository exists, updating..."
  cd repo || exit 1
  git fetch origin "$BRANCH" || {
    log_warn "Git fetch failed"
  }
  git reset --hard "origin/$BRANCH"
  cd ..
fi

cd repo || exit 1
git config user.name "AddonUpdater"
git config user.email "addon-updater@local"

# ===== LOG MODE =====
if [ "$DRY_RUN" = "true" ] || [ "$DRY_RUN" = "True" ]; then
  DRY_MODE=true
  log_dryrun "===== ADDON UPDATER STARTED (Dry Run) ====="
else
  DRY_MODE=false
  log_update "===== ADDON UPDATER STARTED (Live Mode) ====="
fi

# ===== FUNCTION: Get latest tag from Docker Hub or LinuxServer.io =====
get_latest_tag() {
  local image=$1
  local registry="docker"
  local repo_name
  local tags
  local latest_tag

  if echo "$image" | grep -q '^lscr.io/'; then
    registry="linuxserver"
    repo_name=${image#lscr.io/}
  else
    repo_name=$image
  fi

  if [ "$registry" = "linuxserver" ]; then
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/linuxserver/${repo_name}/tags?page_size=100" 2>/dev/null | jq -r '.results[].name') || {
      log_warn "Failed to fetch tags from LinuxServer.io for $repo_name"
      echo ""
      return 1
    }
  else
    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/${repo_name}/tags?page_size=100" 2>/dev/null | jq -r '.results[].name') || {
      log_warn "Failed to fetch tags from Docker Hub for $repo_name"
      echo ""
      return 1
    }
  fi

  # Filter out 'latest', pre-releases, architectures, date tags, etc. Only proper semver-like numeric tags.
  latest_tag=$(echo "$tags" | grep -E '^[0-9]+\.[0-9]+(\.[0-9]+)?$' | sort -Vr | head -n 1)

  if [ -z "$latest_tag" ]; then
    # Fallback: try to find any tag not containing "latest" or alphabets (pre-release)
    latest_tag=$(echo "$tags" | grep -vEi 'latest|rc|alpha|beta|dev|test|[a-z]' | sort -Vr | head -n 1)
  fi

  echo "$latest_tag"
}

# ===== FUNCTION: Send Gotify notification =====
send_gotify() {
  local title=$1
  local message=$2
  local priority=${3:-5}
  [ -z "$GOTIFY_URL" ] && return
  curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
    -F "title=$title" \
    -F "message=$message" \
    -F "priority=$priority" >/dev/null 2>&1

  if [ $? -eq 0 ]; then
    log_info "Gotify notification sent."
  else
    log_warn "Failed to send Gotify notification."
  fi
}

# ===== MAIN LOOP =====
NOTES=""
UPDATED=0

for addon_dir in */; do
  # Skip if no config.json found
  if [ ! -f "${addon_dir}config.json" ]; then
    log_warn "${addon_dir%/}: Missing config.json, skipping."
    continue
  fi

  # Skip .git directory or any hidden
  if [ "${addon_dir%/}" = ".git" ] || [ "${addon_dir%/}" = "repo" ]; then
    continue
  fi

  # Read addon name and image from config.json or build.json or updater.json
  name=$(jq -r '.name // empty' "${addon_dir}config.json")
  image=$(jq -r '.image // empty' "${addon_dir}config.json")

  if [ -z "$image" ]; then
    image=$(jq -r '.build.image // empty' "${addon_dir}build.json" 2>/dev/null)
  fi

  if [ -z "$image" ]; then
    image=$(jq -r '.version.image // empty' "${addon_dir}updater.json" 2>/dev/null)
  fi

  if [ -z "$name" ] || [ -z "$image" ]; then
    log_warn "${addon_dir%/}: Missing name or image, skipping."
    continue
  fi

  # Get current version from config.json, build.json, or updater.json
  current_version=$(jq -r '.version // empty' "${addon_dir}config.json")
  if [ -z "$current_version" ]; then
    current_version=$(jq -r '.version // empty' "${addon_dir}build.json" 2>/dev/null)
  fi
  if [ -z "$current_version" ]; then
    current_version=$(jq -r '.version // empty' "${addon_dir}updater.json" 2>/dev/null)
  fi
  if [ -z "$current_version" ]; then
    current_version="unknown"
  fi

  # Get latest tag from Docker or LinuxServer.io
  latest_version=$(get_latest_tag "$image")
  if [ -z "$latest_version" ]; then
    log_warn "${name}: Could not determine latest version for image '$image'"
    latest_version="$current_version"
  fi

  # Normalize current_version: remove leading 'v' if present for comparison
  normalized_current=$(echo "$current_version" | sed 's/^v//')
  normalized_latest=$(echo "$latest_version" | sed 's/^v//')

  if [ "$normalized_latest" != "$normalized_current" ]; then
    if [ "$DRY_MODE" = true ]; then
      log_dryrun "$name: Update available: $current_version -> $latest_version"
      NOTES="${NOTES}\n🧪 $name: $current_version → $latest_version (simulated)"
    else
      log_update "$name: Updating from $current_version to $latest_version"

      # Update version in files if they exist
      for f in "${addon_dir}"config.json "${addon_dir}"build.json "${addon_dir}"updater.json; do
        if [ -f "$f" ]; then
          jq --arg ver "$latest_version" '.version = $ver' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
        fi
      done

      # Update or create CHANGELOG.md
      changelog="${addon_dir}CHANGELOG.md"
      if [ ! -f "$changelog" ]; then
        echo "# Changelog" > "$changelog"
      fi
      echo -e "\n## $latest_version - $(date '+%Y-%m-%d')\nUpdated from $current_version to $latest_version\nSource: https://hub.docker.com/r/$image/tags" >> "$changelog"

      git add "${addon_dir}"*
      git commit -m "${addon_dir%/}: update version $current_version -> $latest_version"
      UPDATED=$((UPDATED+1))
      NOTES="${NOTES}\n✅ $name: $current_version → $latest_version"
    fi
  else
    log_info "$name: You are running the latest version: $current_version"
    NOTES="${NOTES}\nℹ️ $name: $current_version (up to date)"
  fi
done

# Push changes if live mode and updates were made
if [ "$DRY_MODE" = false ] && [ $UPDATED -gt 0 ]; then
  log_info "Pushing updates to branch $BRANCH"
  git push origin "$BRANCH" || log_warn "Git push failed"
else
  log_info "No updates to push or running in dry run mode."
fi

# Send Gotify notification with summary (always send)
if [ -n "$GOTIFY_URL" ]; then
  TITLE="Addon Updater Report [$(date '+%Y-%m-%d')]"
  # Color code updates green, info gray, simulation cyan for Gotify markdown
  MSG=$(echo -e "$NOTES" | sed \
    -e 's/✅ /<font color="green">✅ /g' \
    -e 's/ℹ️ /<font color="gray">ℹ️ /g' \
    -e 's/🧪 /<font color="cyan">🧪 /g' | sed 's/$/<\/font>/')
  send_gotify "$TITLE" "$MSG" 5
fi

# ===== END =====
log_info "===== ADDON UPDATER FINISHED ====="
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
log_info "Completed in ${ELAPSED}s"
