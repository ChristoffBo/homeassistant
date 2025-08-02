#!/bin/sh
set -e

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Logging functions with Dry Run flag awareness
DRY_RUN=false
VERBOSE=false

log() {
  level="$1"
  shift
  case "$level" in
    INFO) color=$GREEN ;;
    WARN) color=$YELLOW ;;
    ERROR) color=$RED ;;
    DRYRUN) color=$MAGENTA ;;
    *) color=$NC ;;
  esac
  prefix="[$level]"
  # Print messages differently if dry run
  if $DRY_RUN; then
    echo "${color}[DRYRUN]${prefix} $*${NC}"
  else
    echo "${color}${prefix} $*${NC}"
  fi
}

# Load config.json options (assumes options.json in /data/options.json)
if [ ! -f /data/options.json ]; then
  log ERROR "Configuration file /data/options.json not found. Exiting."
  exit 1
fi

# Parse options from options.json using jq
GITUSER=$(jq -r '.gituser // empty' /data/options.json)
GITMAIL=$(jq -r '.gitmail // empty' /data/options.json)
GITAPI=$(jq -r '.gitapi // empty' /data/options.json)
REPOSITORY=$(jq -r '.repository // empty' /data/options.json)
VERBOSE=$(jq -r '.verbose // false' /data/options.json)
DRY_RUN=$(jq -r '.dry_run // false' /data/options.json)
ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications // false' /data/options.json)
GOTIFY_URL=$(jq -r '.gotify_url // empty' /data/options.json)
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' /data/options.json)
GITEA_API_URL=$(jq -r '.gitea_api_url // empty' /data/options.json)
GITEA_TOKEN=$(jq -r '.gitea_token // empty' /data/options.json)

if [ -z "$REPOSITORY" ]; then
  log ERROR "No repository specified in configuration. Exiting."
  exit 1
fi

log INFO "===== ADDON UPDATER STARTED ====="
if $DRY_RUN; then
  log DRYRUN "Dry run mode enabled. No changes will be pushed."
else
  log INFO "Live mode enabled. Changes will be committed and pushed."
fi
log INFO "Repository: $REPOSITORY"

# Setup git user/email and token
export HOME=/tmp
git config --system http.sslVerify false
git config --system credential.helper 'cache --timeout=7200'
git config --system user.name "$GITUSER"
if [ -n "$GITMAIL" ] && [ "$GITMAIL" != "null" ]; then
  git config --system user.email "$GITMAIL"
fi

# Set remote URL with token if token present
if [ -n "$GITAPI" ] && [ "$GITAPI" != "null" ]; then
  REMOTE_URL="https://${GITUSER}:${GITAPI}@github.com/${REPOSITORY}.git"
else
  REMOTE_URL="https://github.com/${REPOSITORY}.git"
fi

# Clone or update repo
BASENAME=$(basename "$REPOSITORY")
REPO_DIR="/data/${BASENAME}"

if [ ! -d "$REPO_DIR" ]; then
  log INFO "Cloning repository $REPOSITORY..."
  if ! git clone --depth=1 "$REMOTE_URL" "$REPO_DIR"; then
    log ERROR "Failed to clone repository $REPOSITORY"
    exit 1
  fi
else
  log INFO "Repository already exists, pulling latest changes..."
  cd "$REPO_DIR" || exit 1
  git reset --hard origin/master
  git pull origin master
fi

cd "$REPO_DIR" || exit 1

# Iterate over addon directories
for addon_dir in */ ; do
  # Check updater.json presence
  if [ ! -f "${addon_dir}updater.json" ]; then
    [ "$VERBOSE" = "true" ] && log WARN "Skipping $addon_dir — updater.json not found."
    continue
  fi

  SLUG=${addon_dir%/}
  [ "$VERBOSE" = "true" ] && log INFO "Processing addon: $SLUG"

  # Load updater.json data
  UPSTREAM=$(jq -r '.upstream_repo // empty' "${addon_dir}updater.json")
  BETA=$(jq -r '.github_beta // false' "${addon_dir}updater.json")
  FULLTAG=$(jq -r '.github_fulltag // false' "${addon_dir}updater.json")
  HAVINGASSET=$(jq -r '.github_havingasset // false' "${addon_dir}updater.json")
  SOURCE=$(jq -r '.source // empty' "${addon_dir}updater.json")
  FILTER_TEXT=$(jq -r '.github_tagfilter // empty' "${addon_dir}updater.json")
  EXCLUDE_TEXT=$(jq -r '.github_exclude // empty' "${addon_dir}updater.json")
  PAUSED=$(jq -r '.paused // false' "${addon_dir}updater.json")
  DATE=$(date '+%Y-%m-%d')
  BYDATE=$(jq -r '.dockerhub_by_date // false' "${addon_dir}updater.json")

  # Skip paused addons
  if [ "$PAUSED" = "true" ]; then
    log WARN "$SLUG updates are paused, skipping."
    continue
  fi

  # Current upstream version
  CURRENT=$(jq -r '.upstream_version // empty' "${addon_dir}updater.json")
  if [ -z "$CURRENT" ]; then
    log WARN "$SLUG upstream_version not found, skipping."
    continue
  fi

  LASTVERSION=""

  if [ "$SOURCE" = "dockerhub" ]; then
    # Docker Hub logic
    DOCKERHUB_REPO=$(echo "$UPSTREAM" | cut -d '/' -f1)
    DOCKERHUB_IMAGE=$(echo "$UPSTREAM" | cut -d '/' -f2)
    LISTSIZE=$(jq -r '.dockerhub_list_size // 100' "${addon_dir}updater.json")

    FILTER_QUERY=""
    [ -n "$FILTER_TEXT" ] && FILTER_QUERY="&name=$FILTER_TEXT"

    # Get list of tags and pick latest valid
    LASTVERSION=$(
      curl -fsSL "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=$LISTSIZE$FILTER_QUERY" \
      | jq -r '.results[].name' \
      | grep -v -E 'latest|dev|nightly|beta' \
      | grep -v "$EXCLUDE_TEXT" \
      | sort -V \
      | tail -n 1
    )

    if [ "$BETA" = "true" ]; then
      LASTVERSION=$(
        curl -fsSL "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=$LISTSIZE$FILTER_QUERY" \
        | jq -r '.results[].name' \
        | grep dev \
        | grep -v "$EXCLUDE_TEXT" \
        | sort -V \
        | tail -n 1
      )
    fi

    if [ "$BYDATE" = "true" ]; then
      LASTVERSION=$(
        curl -fsSL "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=$LISTSIZE&ordering=last_updated$FILTER_QUERY" \
        | jq -r '.results[].name' \
        | grep -v -E 'latest|dev|nightly|beta' \
        | grep -v "$EXCLUDE_TEXT" \
        | sort -V \
        | tail -n 1
      )
      # Get last_updated date
      LASTDATE=$(
        curl -fsSL "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags/?page_size=$LISTSIZE&ordering=last_updated$FILTER_QUERY" \
        | jq -r --arg v "$LASTVERSION" '.results[] | select(.name==$v) | .last_updated' \
        | cut -d 'T' -f1
      )
      LASTVERSION="${LASTVERSION}-${LASTDATE}"
    fi

  else
    # Use lastversion binary for github, gitea or others
    ARGS="--at $SOURCE"
    [ "$FULLTAG" = "true" ] && ARGS="$ARGS --format tag"
    [ "$HAVINGASSET" = "true" ] && ARGS="$ARGS --having-asset"
    [ -n "$FILTER_TEXT" ] && ARGS="$ARGS --only $FILTER_TEXT"
    [ -n "$EXCLUDE_TEXT" ] && ARGS="$ARGS --exclude $EXCLUDE_TEXT"
    [ "$BETA" = "true" ] && ARGS="$ARGS --pre"

    # Try to get lastversion, fallback to packages if no release found
    LASTVERSION=$(lastversion "$UPSTREAM" $ARGS 2>/dev/null || true)

    if [ -z "$LASTVERSION" ]; then
      log WARN "$SLUG: No release found, checking packages fallback."
      last_packages="$(curl -sL "https://github.com/${UPSTREAM}/packages" | grep -oP '/container/package/\K[^"]+' | head -n 1)"
      if [ -n "$last_packages" ]; then
        LASTVERSION=$(curl -sL "https://github.com/${UPSTREAM}/pkgs/container/${last_packages}" \
          | grep -oP 'tag=\K[^"]+' \
          | grep -v -E 'latest|dev|nightly|beta' \
          | sort -V | tail -n 1)
        if [ -z "$LASTVERSION" ]; then
          log WARN "$SLUG: No package versions found."
          continue
        fi
      else
        log WARN "$SLUG: No packages found fallback."
        continue
      fi
    fi
  fi

  # Clean versions for comparison
  LASTVERSION_CLEAN=$(echo "$LASTVERSION" | tr -d '"')
  CURRENT_CLEAN=$(echo "$CURRENT" | tr -d '"')

  if [ "$CURRENT_CLEAN" != "$LASTVERSION_CLEAN" ]; then
    log INFO "$SLUG: Update available: $CURRENT -> $LASTVERSION_CLEAN"

    # Update versions in files
    for file in config.json config.yaml Dockerfile build.json build.yaml; do
      if [ -f "${addon_dir}${file}" ]; then
        sed -i "s/${CURRENT}/${LASTVERSION}/g" "${addon_dir}${file}" || true
      fi
    done

    # Safely update config.json version
    if [ -f "${addon_dir}config.json" ]; then
      tmp=$(mktemp)
      jq --arg ver "$LASTVERSION_CLEAN" '.version = $ver' "${addon_dir}config.json" > "$tmp" && mv "$tmp" "${addon_dir}config.json"
    elif [ -f "${addon_dir}config.yaml" ]; then
      sed -i "/version:/c\version: \"$LASTVERSION_CLEAN\"" "${addon_dir}config.yaml"
    fi

    # Update updater.json version and last_update
    tmp=$(mktemp)
    jq --arg ver "$LASTVERSION_CLEAN" --arg date "$DATE" \
      '.upstream_version = $ver | .last_update = $date' "${addon_dir}updater.json" > "$tmp" && mv "$tmp" "${addon_dir}updater.json"

    # Update CHANGELOG.md
    changelog="${addon_dir}CHANGELOG.md"
    touch "$changelog"
    if echo "$UPSTREAM" | grep -q "github"; then
      sed -i "1i - Update to latest version from $UPSTREAM (changelog: https://github.com/${UPSTREAM%/}/releases)" "$changelog"
    else
      sed -i "1i - Update to latest version from $UPSTREAM" "$changelog"
    fi
    sed -i "1i ## $LASTVERSION_CLEAN ($DATE)" "$changelog"
    sed -i "1i " "$changelog"

    log INFO "$SLUG: Files updated."

    # Commit and push changes
    git add -A
    git commit -m "Updater bot: $SLUG updated to $LASTVERSION_CLEAN" >/dev/null 2>&1 || true

    git remote set-url origin "$REMOTE_URL"

    if ! $DRY_RUN; then
      if git push; then
        log INFO "$SLUG: Changes pushed to repository."
      else
        log ERROR "$SLUG: Failed to push changes."
      fi
    else
      log DRYRUN "$SLUG: Dry run active, not pushing changes."
    fi

    # Optionally send notifications (Gotify or Gitea)
    if $ENABLE_NOTIFICATIONS; then
      message="$SLUG updated from $CURRENT_CLEAN to $LASTVERSION_CLEAN"
      # Gotify notification
      if [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
        curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
          -H "Content-Type: application/json" \
          -d "{\"title\":\"Addon Updater\", \"message\":\"$message\", \"priority\":5}" >/dev/null 2>&1
      fi
      # Gitea notification (example webhook)
      if [ -n "$GITEA_API_URL" ] && [ -n "$GITEA_TOKEN" ]; then
        curl -s -X POST "$GITEA_API_URL" \
          -H "Content-Type: application/json" \
          -H "Authorization: token $GITEA_TOKEN" \
          -d "{\"text\":\"$message\"}" >/dev/null 2>&1
      fi
    fi

  else
    log INFO "$SLUG: Already up-to-date ($CURRENT_CLEAN)."
  fi
done

log INFO "===== ADDON UPDATER FINISHED ====="

# Cleanup dry run cloned data
if $DRY_RUN; then
  rm -rf /data/*
  log DRYRUN "Dry run cleanup done."
fi

exit 0
