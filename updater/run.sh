#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config
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
  local type=$(jq -r '.notifier.type' "$CONFIG_PATH")
  local url=$(jq -r '.notifier.url' "$CONFIG_PATH")
  local token=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")

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

fetch_latest_tag() {
  local repo="$1"
  local api_url="https://hub.docker.com/v2/repositories/$repo/tags?page_size=100"

  # Log to stderr so stdout is clean (only the tag)
  >&2 log "$COLOR_BLUE" "🔍 Fetching tags from Docker Hub API: $api_url"

  local tags_json
  tags_json=$(curl -sS "$api_url")

  # Validate JSON contains 'results'
  if ! echo "$tags_json" | jq -e '.results' > /dev/null 2>&1; then
    echo ""  # Return empty string if no tags found
    return 1
  fi

  # Extract latest tag ignoring 'latest' and 'rc'
  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v -E 'latest|rc' | sort -Vr | head -n1)

  echo "$latest_tag"
}

# Git push helper
git_push() {
  local url="$1"
  local username="$2"
  local token="$3"

  if [[ -z "$url" || -z "$username" || -z "$token" ]]; then
    log "$COLOR_YELLOW" "⚠️ Repository URL, username, or token not configured, skipping git push."
    return 1
  fi

  # Remove trailing .git if present
  url="${url%.git}"

  # Insert credentials into URL for push
  local auth_url
  auth_url="${url/https:\/\//https:\/\/$username:$token@}"

  git remote set-url origin "$auth_url"
  if git push origin main; then
    log "$COLOR_GREEN" "✅ Git push successful."
  else
    log "$COLOR_RED" "❌ Git push failed."
  fi
}

# Main update logic
cd "$REPO_DIR"
UPDATED=0
NOTIFY_MSG=""

# Read cron from config
CRON_SCHEDULE=$(jq -r '.cron // empty' "$CONFIG_PATH")
if [[ -z "$CRON_SCHEDULE" ]]; then
  log "$COLOR_YELLOW" "⚠️ Cron schedule not set, script will exit after this run."
  EXIT_AFTER_RUN=1
else
  EXIT_AFTER_RUN=0
fi

for addon_config in */config.json; do
  ADDON_DIR=$(dirname "$addon_config")
  NAME=$(jq -r '.name' "$addon_config")

  # Try to read version and image from config.json, build.json, then updater.json
  VERSION=$(jq -r '.version // empty' "$addon_config")
  IMAGE=$(jq -r '.image // empty' "$addon_config")

  for file in build.json updater.json; do
    if [[ -f "$REPO_DIR/$ADDON_DIR/$file" ]]; then
      [[ -z "$VERSION" || "$VERSION" == "null" ]] && VERSION=$(jq -r '.version // empty' "$REPO_DIR/$ADDON_DIR/$file")
      [[ -z "$IMAGE" || "$IMAGE" == "null" ]] && IMAGE=$(jq -r '.image // empty' "$REPO_DIR/$ADDON_DIR/$file")
    fi
  done

  if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$NAME' has no Docker image defined, skipping."
    continue
  fi

  log "$COLOR_PURPLE" "\n🧩 Addon: $NAME"
  log "$COLOR_BLUE" "🔢 Current version: ${VERSION:-none}"
  log "$COLOR_BLUE" "📦 Image: $IMAGE"

  # Parse image repo and tag
  # Support multi-arch images in JSON objects, fallback to string
  if echo "$IMAGE" | jq -e . >/dev/null 2>&1; then
    # JSON object, pick architecture matching $ARCH or fallback to amd64
    ARCH=$(uname -m)
    case "$ARCH" in
      x86_64) ARCH="amd64" ;;
      aarch64) ARCH="aarch64" ;;
      armv7*) ARCH="armv7" ;;
      *) ARCH="amd64" ;;
    esac
    IMAGE=$(echo "$IMAGE" | jq -r --arg arch "$ARCH" '.[$arch] // .amd64 // ""')
    if [[ -z "$IMAGE" ]]; then
      log "$COLOR_RED" "❌ No image found for architecture '$ARCH' for addon '$NAME', skipping."
      continue
    fi
  fi

  # Split IMAGE into repo and tag
  REPO="${IMAGE%:*}"
  TAG="${IMAGE##*:}"

  # Check and handle "latest" or any unsupported tags
  if [[ "$TAG" == "latest" || "$TAG" =~ latest ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$NAME' uses 'latest' tag; will try to find latest specific version tag."
    CLEAN_REPO="$REPO"
    # Remove lscr.io prefix if present for Docker Hub API compatibility
    CLEAN_REPO="${CLEAN_REPO#lscr.io/}"
    CLEAN_REPO="${CLEAN_REPO#docker.io/}"

    # Fetch latest tag from Docker Hub API
    LATEST_TAG=$(fetch_latest_tag "$CLEAN_REPO")

    if [[ -z "$LATEST_TAG" ]]; then
      log "$COLOR_RED" "❌ Could not fetch tags for $CLEAN_REPO"
      continue
    fi
  else
    LATEST_TAG="$TAG"
  fi

  log "$COLOR_GREEN" "🚀 Latest version: $LATEST_TAG"
  log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

  # Normalize versions to ignore arch prefixes like amd64-
  NORMALIZED_CURRENT=$(echo "$VERSION" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')
  NORMALIZED_LATEST=$(echo "$LATEST_TAG" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

  if [[ "$NORMALIZED_CURRENT" != "$NORMALIZED_LATEST" ]]; then
    log "$COLOR_YELLOW" "⬆️  Updating $NAME from $VERSION to $LATEST_TAG"

    # Update versions in all 3 files if they exist
    for file in config.json build.json updater.json; do
      if [[ -f "$REPO_DIR/$ADDON_DIR/$file" ]]; then
        jq --arg ver "$LATEST_TAG" '.version = $ver' "$REPO_DIR/$ADDON_DIR/$file" > tmp.$$.json && mv tmp.$$.json "$REPO_DIR/$ADDON_DIR/$file"
      fi
    done

    # Update CHANGELOG.md (create if missing)
    CHANGELOG="$REPO_DIR/$ADDON_DIR/CHANGELOG.md"
    if [[ ! -f "$CHANGELOG" ]]; then
      echo "# Changelog" > "$CHANGELOG"
    fi
    echo -e "\n## $LATEST_TAG - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$VERSION\` to \`$LATEST_TAG\`" >> "$CHANGELOG"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $NAME"

    UPDATED=1
    NOTIFY_MSG+="⬆️ Updated $NAME: $VERSION → $LATEST_TAG\n"
  else
    log "$COLOR_GREEN" "✔️ $NAME is already up to date ($VERSION)"
  fi
  log "$COLOR_BLUE" "----------------------------"
done

if [[ $UPDATED -eq 1 ]]; then
  send_notification "📦 Add-ons updated:\n$NOTIFY_MSG"
else
  log "$COLOR_GREEN" "✅ No updates needed."
fi

# Git operations
GIT_URL=$(jq -r '.github.url // empty' "$CONFIG_PATH")
GIT_USERNAME=$(jq -r '.github.username // empty' "$CONFIG_PATH")
GIT_TOKEN=$(jq -r '.github.token // empty' "$CONFIG_PATH")

if [[ $UPDATED -eq 1 && -n "$GIT_URL" && -n "$GIT_USERNAME" && -n "$GIT_TOKEN" ]]; then
  cd "$REPO_DIR"
  git config user.name "$GIT_USERNAME"
  git config user.email "$GIT_USERNAME@users.noreply.github.com"
  git add .
  git commit -m "Update add-on versions $(date '+%Y-%m-%d %H:%M:%S')" || true

  # Remove trailing .git if present
  GIT_URL="${GIT_URL%.git}"

  # Use credentials in URL
  AUTH_URL="${GIT_URL/https:\/\//https:\/\/$GIT_USERNAME:$GIT_TOKEN@}"

  git remote set-url origin "$AUTH_URL"
  if git push origin main; then
    log "$COLOR_GREEN" "✅ Git push successful."
  else
    log "$COLOR_RED" "❌ Git push failed."
  fi
else
  if [[ $UPDATED -eq 1 ]]; then
    log "$COLOR_YELLOW" "⚠️ Git credentials missing, skipping push."
  fi
fi

# Cron handling (run script indefinitely if cron set)
if [[ -z "$CRON_SCHEDULE" ]]; then
  log "$COLOR_YELLOW" "⚠️ Cron not configured, exiting after this run."
  exit 0
else
  log "$COLOR_GREEN" "🕒 Starting cron with schedule: $CRON_SCHEDULE"
fi

# Start cron with the schedule from GUI
cron -f &

# Create cronjob file
echo "$CRON_SCHEDULE /run.sh" > /etc/crontabs/root

# Keep script alive
while true; do
  sleep 60
done
