#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config (default UTC)
TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ

# Colored output codes
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  echo -e "[\033[90m$(date '+%Y-%m-%d %H:%M:%S %Z')\033[0m] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

send_notification() {
  local message="$1"
  local type url token

  type=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
  url=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
  token=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")

  # If any required notifier config missing, skip
  if [[ -z "$type" || -z "$url" ]]; then
    return
  fi

  case "$type" in
    gotify)
      curl -s -X POST "$url/message" \
        -H "X-Gotify-Key: $token" \
        -F "title=Addon Updater" \
        -F "message=$message" \
        -F "priority=5" > /dev/null || true
      ;;
    mailrise)
      curl -s -X POST "$url" -H "Content-Type: text/plain" --data "$message" > /dev/null || true
      ;;
    apprise)
      curl -s "$url" -d "$message" > /dev/null || true
      ;;
    *)
      log "$COLOR_RED" "❌ Unknown notifier type: $type"
      ;;
  esac
}

# Get latest Docker tag for a repo from Docker Hub, excluding 'latest', rc, beta, alpha etc.
get_latest_docker_tag() {
  local repo="$1"

  # Strip known registry prefixes for Docker Hub API compatibility
  local clean_repo="$repo"
  clean_repo=${clean_repo#lscr.io/}
  clean_repo=${clean_repo#docker.io/}

  local api_url="https://hub.docker.com/v2/repositories/$clean_repo/tags?page_size=100"

  log "$COLOR_BLUE" "🔍 Fetching tags from Docker Hub API: $api_url"

  local tags_json
  tags_json=$(curl -s "$api_url" || echo "{}")

  # Validate 'results' is an array
  if ! jq -e '.results | arrays' <<< "$tags_json" >/dev/null 2>&1; then
    log "$COLOR_RED" "❌ Invalid or empty API response for repo: $clean_repo"
    log "$COLOR_RED" "API Response: $tags_json"
    echo ""
    return
  fi

  local latest_tag
  latest_tag=$(jq -r '.results[].name' <<< "$tags_json" | grep -v -E 'latest|rc|beta|alpha' | sort -Vr | head -n1)

  echo "$latest_tag"
}

# Git push using URL without .git suffix
git_push() {
  local repo_dir="$1"
  local repo_url token

  repo_url=$(jq -r '.repository.url // empty' "$CONFIG_PATH")
  token=$(jq -r '.repository.token // empty' "$CONFIG_PATH")

  if [[ -z "$repo_url" ]]; then
    log "$COLOR_RED" "❌ Repository URL not configured, skipping git push."
    return 1
  fi

  # Strip trailing .git if present
  repo_url="${repo_url%.git}"

  # Inject token if provided, expect repo URL like https://github.com/username/repo
  if [[ -n "$token" ]]; then
    repo_url="${repo_url/https:\/\//https://$token@}"
  fi

  log "$COLOR_BLUE" "📤 Pushing changes to GitHub repo $repo_url"

  (
    cd "$repo_dir"
    git add .
    git commit -m "Update add-ons versions and changelogs [skip ci]" || true
    git push "$repo_url" HEAD || {
      log "$COLOR_RED" "❌ Git push failed."
      return 1
    }
  )
}

# Main logic
cd "$REPO_DIR"

UPDATED=0
NOTIFY_MSG=""

for addon_config in */config.json; do
  ADDON_DIR=$(dirname "$addon_config")
  NAME=$(jq -r '.name // empty' "$addon_config")
  CURRENT_VERSION=""
  IMAGE=""

  # Load image and version from config.json, build.json, updater.json in order
  for file in "$REPO_DIR/$ADDON_DIR/config.json" "$REPO_DIR/$ADDON_DIR/build.json" "$REPO_DIR/$ADDON_DIR/updater.json"; do
    if [[ -f "$file" ]]; then
      [[ -z "$IMAGE" ]] && IMAGE=$(jq -r '.image // empty' "$file")
      [[ -z "$CURRENT_VERSION" ]] && CURRENT_VERSION=$(jq -r '.version // empty' "$file")
    fi
  done

  log "$COLOR_PURPLE" "\n🧩 Addon: $ADDON_DIR"
  log "$COLOR_BLUE" "🔢 Current version: ${CURRENT_VERSION:-'unknown'}"
  log "$COLOR_BLUE" "📦 Image: ${IMAGE:-'none'}"

  if [[ -z "$IMAGE" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$ADDON_DIR' has no Docker image defined, skipping."
    log "$COLOR_BLUE" "----------------------------"
    continue
  fi

  # Extract repo and tag from image (supports multi-arch JSON)
  if jq -e 'type == "object"' <<< "$IMAGE" >/dev/null 2>&1; then
    # Multi-arch: pick amd64 if exists, else first arch key
    ARCH_TAG=$(jq -r '."amd64" // (to_entries[0].value)' <<< "$IMAGE")
    IMAGE="$ARCH_TAG"
    log "$COLOR_YELLOW" "⚠️ Multi-arch image detected, using: $IMAGE"
  fi

  REPO="${IMAGE%:*}"
  TAG="${IMAGE##*:}"

  # Handle 'latest' tag by fetching latest non-latest version tag
  if [[ "$TAG" == "latest" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$ADDON_DIR' uses 'latest' tag; will try to find latest specific version tag."
    LATEST_TAG=$(get_latest_docker_tag "$REPO")
    if [[ -z "$LATEST_TAG" ]]; then
      log "$COLOR_RED" "❌ Could not fetch tags for $REPO"
      log "$COLOR_BLUE" "----------------------------"
      continue
    fi
  else
    LATEST_TAG="$TAG"
  fi

  # Normalize tags (remove arch prefixes)
  NORMALIZED_CURRENT=$(echo "$CURRENT_VERSION" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')
  NORMALIZED_LATEST=$(echo "$LATEST_TAG" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

  log "$COLOR_GREEN" "🚀 Latest version: $LATEST_TAG"
  log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

  # Compare normalized versions; update if different
  if [[ "$NORMALIZED_CURRENT" != "$NORMALIZED_LATEST" ]]; then
    log "$COLOR_YELLOW" "⬆️  Updating $ADDON_DIR from $CURRENT_VERSION to $LATEST_TAG"

    # Update version in all files if exist
    for file in "$REPO_DIR/$ADDON_DIR/config.json" "$REPO_DIR/$ADDON_DIR/build.json" "$REPO_DIR/$ADDON_DIR/updater.json"; do
      if [[ -f "$file" ]]; then
        jq --arg ver "$LATEST_TAG" '.version = $ver' "$file" > tmp.$$.json && mv tmp.$$.json "$file"
      fi
    done

    # Update CHANGELOG.md - create if missing
    CHANGELOG="$REPO_DIR/$ADDON_DIR/CHANGELOG.md"
    if [[ ! -f "$CHANGELOG" ]]; then
      echo "# Changelog" > "$CHANGELOG"
    fi
    echo -e "\n## $LATEST_TAG - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$CURRENT_VERSION\` to \`$LATEST_TAG\`" >> "$CHANGELOG"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $ADDON_DIR"

    UPDATED=1
    NOTIFY_MSG+="⬆️ Updated $NAME from $CURRENT_VERSION to $LATEST_TAG\n"
  else
    log "$COLOR_GREEN" "✔️ $ADDON_DIR is already up to date ($CURRENT_VERSION)"
  fi

  log "$COLOR_BLUE" "----------------------------"
done

if [[ $UPDATED -eq 1 ]]; then
  git_push "$REPO_DIR"
  send_notification "$NOTIFY_MSG"
else
  log "$COLOR_GREEN" "✅ No updates needed."
fi

# Handle cron schedule from config, else exit
CRON_SCHEDULE=$(jq -r '.cron // empty' "$CONFIG_PATH")
if [[ -z "$CRON_SCHEDULE" ]]; then
  log "$COLOR_YELLOW" "⚠️ Cron schedule not found in config, exiting after this run."
  exit 0
fi

# Start cron with schedule from config (in container)
log "$COLOR_BLUE" "⏰ Starting cron with schedule: $CRON_SCHEDULE"
echo "$CRON_SCHEDULE /usr/bin/env bash /run.sh" > /etc/crontabs/root
crond -f
