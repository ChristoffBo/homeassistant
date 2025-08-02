#!/bin/sh
set -e

# Fix git fatal error
export HOME=/tmp

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log() {
  level=$1
  shift
  color=$NC
  case "$level" in
    INFO) color=$CYAN ;;
    WARN) color=$YELLOW ;;
    ERROR) color=$RED ;;
    DRYRUN) color=$MAGENTA ;;
  esac
  printf "%b[%s] %s%b\n" "$color" "$level" "$*" "$NC"
}

# Load config - replace these with your method to read from options.json or env
GITUSER="${gituser:-ChristoffBo}"
GITMAIL="${gitmail:-your@email.com}"
GITAPI="${gitapi:-}"       # GitHub personal access token
REPOSITORY="${repository:-ChristoffBo/homeassistant}"
VERBOSE="${verbose:-true}"
DRY_RUN="${dry_run:-true}"
ENABLE_NOTIFICATIONS="${enable_notifications:-true}"
GOTIFY_URL="${gotify_url:-http://10.0.0.99:8091}"
GOTIFY_TOKEN="${gotify_token:-}"
GITEA_API_URL="${gitea_api_url:-}"
GITEA_TOKEN="${gitea_token:-}"

log INFO "===== ADDON UPDATER STARTED ====="

if [ "$DRY_RUN" = "true" ]; then
  log DRYRUN "Dry run mode enabled. No changes will be pushed."
fi

log INFO "Repository: $REPOSITORY"

# Setup git config
git config --system http.sslVerify false
git config --system credential.helper 'cache --timeout=7200'
git config --system user.name "$GITUSER"
[ -n "$GITMAIL" ] && git config --system user.email "$GITMAIL"

# Clone or update repo
REPO_BASENAME=$(basename "$REPOSITORY")

if [ ! -d "/data/$REPO_BASENAME" ]; then
  log INFO "Cloning repository $REPOSITORY..."
  git clone "https://github.com/$REPOSITORY" "/data/$REPO_BASENAME"
else
  log INFO "Updating repository $REPOSITORY..."
  cd "/data/$REPO_BASENAME" || exit 1
  git reset --hard
  git clean -fd
  git pull --rebase origin main || git reset --hard origin/main
fi

cd "/data/$REPO_BASENAME" || exit 1

# Set remote with token for push (only if not dry run)
if [ "$DRY_RUN" != "true" ] && [ -n "$GITAPI" ]; then
  git remote set-url origin "https://${GITUSER}:${GITAPI}@github.com/${REPOSITORY}" > /dev/null 2>&1 || true
fi

# Process each addon folder
for addon_dir in */; do
  [ ! -f "${addon_dir}updater.json" ] && log WARN "Skipping ${addon_dir%/}, updater.json not found" && continue

  SLUG=${addon_dir%/}

  # Load updater.json fields
  UPSTREAM=$(jq -r .upstream_repo "${addon_dir}updater.json")
  BETA=$(jq -r .github_beta "${addon_dir}updater.json")
  FULLTAG=$(jq -r .github_fulltag "${addon_dir}updater.json")
  HAVINGASSET=$(jq -r .github_havingasset "${addon_dir}updater.json")
  SOURCE=$(jq -r .source "${addon_dir}updater.json")
  FILTER_TEXT=$(jq -r .github_tagfilter "${addon_dir}updater.json")
  EXCLUDE_TEXT=$(jq -r .github_exclude "${addon_dir}updater.json")
  PAUSED=$(jq -r .paused "${addon_dir}updater.json")
  CURRENT=$(jq -r .upstream_version "${addon_dir}updater.json")

  # Skip paused addons
  if [ "$PAUSED" = "true" ]; then
    log WARN "$SLUG updates are paused, skipping"
    continue
  fi

  [ "$EXCLUDE_TEXT" = "null" ] && EXCLUDE_TEXT="zzzzzzzzzzzzzzzz"

  # Get latest version
  LASTVERSION=""
  DATE=$(date +%Y-%m-%d)

  if [ "$SOURCE" = "dockerhub" ]; then
    DOCKERHUB_REPO="${UPSTREAM%%/*}"
    DOCKERHUB_IMAGE=$(echo "$UPSTREAM" | cut -d "/" -f2)
    LISTSIZE=100

    FILTER_QUERY=""
    if [ -n "$FILTER_TEXT" ] && [ "$FILTER_TEXT" != "null" ]; then
      FILTER_QUERY="&name=$FILTER_TEXT"
    fi

    LASTVERSION=$(
      curl -fsSL "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=${LISTSIZE}${FILTER_QUERY}" \
      | jq -r '.results[].name' \
      | grep -vE 'latest|dev|nightly|beta' \
      | grep -v "$EXCLUDE_TEXT" \
      | sort -V \
      | tail -n 1
    )

  else
    # For github or other source - using lastversion tool
    ARGS="--at $SOURCE"
    [ "$FULLTAG" = "true" ] && ARGS="$ARGS --format tag"
    [ "$HAVINGASSET" = "true" ] && ARGS="$ARGS --having-asset"
    [ -n "$FILTER_TEXT" ] && [ "$FILTER_TEXT" != "null" ] && ARGS="$ARGS --only $FILTER_TEXT"
    [ -n "$EXCLUDE_TEXT" ] && [ "$EXCLUDE_TEXT" != "null" ] && ARGS="$ARGS --exclude $EXCLUDE_TEXT"
    [ "$BETA" = "true" ] && ARGS="$ARGS --pre"

    LASTVERSION=$(lastversion "$UPSTREAM" $ARGS 2>/dev/null || echo "")

    if [ -z "$LASTVERSION" ]; then
      log WARN "$SLUG: No release found, fallback to packages if GitHub..."
      # Add fallback logic here if desired
    fi
  fi

  LASTVERSION_CLEAN=$(echo "$LASTVERSION" | tr -d '"')
  CURRENT_CLEAN=$(echo "$CURRENT" | tr -d '"')

  if [ "$LASTVERSION_CLEAN" != "$CURRENT_CLEAN" ]; then
    log INFO "$SLUG: Update available: $CURRENT_CLEAN -> $LASTVERSION_CLEAN"

    # Update files config.json, build.json, updater.json, etc.
    for file in config.json build.json updater.json; do
      if [ -f "${addon_dir}${file}" ]; then
        sed -i "s/$CURRENT_CLEAN/$LASTVERSION_CLEAN/g" "${addon_dir}${file}"
      fi
    done

    # Update version fields explicitly
    if [ -f "${addon_dir}config.json" ]; then
      jq --arg ver "$LASTVERSION_CLEAN" '.version = $ver' "${addon_dir}config.json" | sponge "${addon_dir}config.json"
    fi

    jq --arg ver "$LASTVERSION_CLEAN" --arg date "$DATE" '.upstream_version = $ver | .last_update = $date' "${addon_dir}updater.json" | sponge "${addon_dir}updater.json"

    # Update changelog
    CHANGELOG="${addon_dir}CHANGELOG.md"
    touch "$CHANGELOG"
    {
      echo "## $LASTVERSION_CLEAN ($DATE)"
      echo "- Update to latest version from $UPSTREAM"
      echo ""
      cat "$CHANGELOG"
    } > "${CHANGELOG}.tmp" && mv "${CHANGELOG}.tmp" "$CHANGELOG"

    # Commit changes
    git add -A "${addon_dir}"
    git commit -m "Updater bot: $SLUG updated to $LASTVERSION_CLEAN" >/dev/null 2>&1 || true

    if [ "$DRY_RUN" = "true" ]; then
      log DRYRUN "$SLUG updated to $LASTVERSION_CLEAN (dry run - no push)"
    else
      git push origin main || log ERROR "Failed to push changes for $SLUG"
    fi

    # Notifications
    if [ "$ENABLE_NOTIFICATIONS" = "true" ] && [ "$DRY_RUN" != "true" ]; then
      if [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
        curl -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
          -H "Content-Type: application/json" \
          -d "{\"title\":\"Addon Update\",\"message\":\"$SLUG updated to $LASTVERSION_CLEAN\",\"priority\":5}" \
          >/dev/null 2>&1 || log WARN "Failed to send Gotify notification"
      fi
      if [ -n "$GITEA_API_URL" ] && [ -n "$GITEA_TOKEN" ]; then
        # Implement Gitea notification here if needed
        :
      fi
    fi

  else
    log INFO "$SLUG is already up to date ($CURRENT_CLEAN)"
  fi
done

log INFO "===== ADDON UPDATER FINISHED ====="
