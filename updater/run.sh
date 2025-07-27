#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load timezone from config
TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ

# Colors for logging
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

# Fetch latest docker tag (ignores latest, rc, beta, alpha)
get_latest_docker_tag() {
  local repo="$1"
  local clean_repo="$repo"

  # Strip registry prefixes like lscr.io/ or docker.io/
  clean_repo=${clean_repo#lscr.io/}
  clean_repo=${clean_repo#docker.io/}

  local api_url="https://hub.docker.com/v2/repositories/$clean_repo/tags?page_size=100"

  local tags_json
  tags_json=$(curl -s "$api_url" || echo "{}")

  # Validate json and presence of results
  if ! jq -e '.results | arrays' <<< "$tags_json" >/dev/null 2>&1; then
    echo ""
    return
  fi

  # Extract tags, filter out 'latest' and pre-releases, sort, return highest
  jq -r '.results[].name' <<< "$tags_json" | grep -v -E 'latest|rc|beta|alpha' | sort -Vr | head -n1
}

# Git setup
REPO_URL=$(jq -r '.repository.url // empty' "$CONFIG_PATH" | sed 's/\.git$//')
GIT_USERNAME=$(jq -r '.repository.username // empty' "$CONFIG_PATH")
GIT_TOKEN=$(jq -r '.repository.token // empty' "$CONFIG_PATH")

if [[ -n "$REPO_URL" && -n "$GIT_USERNAME" && -n "$GIT_TOKEN" ]]; then
  # Insert token auth into repo URL for pushing
  AUTH_REPO_URL="${REPO_URL/https:\/\//https://${GIT_USERNAME}:${GIT_TOKEN}@}"
else
  AUTH_REPO_URL=""
fi

cd "$REPO_DIR"
UPDATED=0
UPDATE_MSG=""

for addon_config in */config.json; do
  ADDON_DIR=$(dirname "$addon_config")
  NAME=$(jq -r '.name' "$REPO_DIR/$addon_config" 2>/dev/null || echo "$ADDON_DIR")
  
  # Determine image from config.json, fallback build.json then updater.json
  IMAGE=$(jq -r '.image // empty' "$REPO_DIR/$ADDON_DIR/config.json" 2>/dev/null)
  if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
    IMAGE=$(jq -r '.image // empty' "$REPO_DIR/$ADDON_DIR/build.json" 2>/dev/null)
  fi
  if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
    IMAGE=$(jq -r '.image // empty' "$REPO_DIR/$ADDON_DIR/updater.json" 2>/dev/null)
  fi

  # Get current version from config.json, fallback build.json then updater.json
  CURRENT_VERSION=$(jq -r '.version // empty' "$REPO_DIR/$ADDON_DIR/config.json" 2>/dev/null)
  if [[ -z "$CURRENT_VERSION" || "$CURRENT_VERSION" == "null" ]]; then
    CURRENT_VERSION=$(jq -r '.version // empty' "$REPO_DIR/$ADDON_DIR/build.json" 2>/dev/null)
  fi
  if [[ -z "$CURRENT_VERSION" || "$CURRENT_VERSION" == "null" ]]; then
    CURRENT_VERSION=$(jq -r '.version // empty' "$REPO_DIR/$ADDON_DIR/updater.json" 2>/dev/null)
  fi

  log "$COLOR_PURPLE" "\n🧩 Addon: $NAME"
  log "$COLOR_BLUE" "🔢 Current version: $CURRENT_VERSION"
  log "$COLOR_BLUE" "📦 Image: $IMAGE"

  if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$NAME' has no Docker image defined, skipping."
    log "$COLOR_BLUE" "----------------------------"
    continue
  fi

  # Extract repo and tag from image
  REPO="${IMAGE%:*}"
  TAG="${IMAGE##*:}"

  # Handle images that are JSON objects with arch keys
  if jq -e . >/dev/null 2>&1 <<<"$IMAGE"; then
    # It's JSON, parse for current arch or amd64 fallback
    ARCH=$(uname -m)
    case "$ARCH" in
      x86_64) ARCH="amd64" ;;
      aarch64) ARCH="aarch64" ;;
      armv7*) ARCH="armv7" ;;
      *) ARCH="amd64" ;; # fallback
    esac
    IMAGE=$(jq -r --arg arch "$ARCH" '.[$arch] // .amd64 // empty' <<< "$IMAGE")
    if [[ -z "$IMAGE" ]]; then
      log "$COLOR_YELLOW" "⚠️ No image found for arch '$ARCH', skipping."
      log "$COLOR_BLUE" "----------------------------"
      continue
    fi
    REPO="${IMAGE%:*}"
    TAG="${IMAGE##*:}"
  fi

  # If tag is latest or contains 'latest', try to find latest specific tag
  if [[ "$TAG" == "latest" || "$TAG" == *"latest"* ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$NAME' uses 'latest' tag; will try to find latest specific version tag."
    LATEST_TAG=$(get_latest_docker_tag "$REPO")
    if [[ -z "$LATEST_TAG" ]]; then
      log "$COLOR_RED" "❌ Could not fetch tags for $REPO"
      log "$COLOR_BLUE" "----------------------------"
      continue
    fi
  else
    LATEST_TAG="$TAG"
  fi

  log "$COLOR_GREEN" "🚀 Latest version: $LATEST_TAG"
  log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

  # Normalize tags by removing arch prefix (amd64-, armhf-, etc)
  NORMALIZED_CURRENT=$(echo "$CURRENT_VERSION" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')
  NORMALIZED_LATEST=$(echo "$LATEST_TAG" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

  if [[ "$NORMALIZED_CURRENT" != "$NORMALIZED_LATEST" ]]; then
    log "$COLOR_YELLOW" "⬆️  Updating $NAME from $CURRENT_VERSION to $LATEST_TAG"

    # Update version in build.json, updater.json and config.json if they exist
    for jsonfile in build.json updater.json config.json; do
      FILE="$REPO_DIR/$ADDON_DIR/$jsonfile"
      if [[ -f "$FILE" ]]; then
        jq --arg ver "$LATEST_TAG" '.version = $ver' "$FILE" > tmp.$$.json && mv tmp.$$.json "$FILE"
      fi
    done

    # Update CHANGELOG.md (create if missing)
    CHANGELOG="$REPO_DIR/$ADDON_DIR/CHANGELOG.md"
    if [[ ! -f "$CHANGELOG" ]]; then
      echo "# Changelog" > "$CHANGELOG"
    fi
    echo -e "\n## $LATEST_TAG - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$CURRENT_VERSION\` to \`$LATEST_TAG\`" >> "$CHANGELOG"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $NAME"

    UPDATED=1
    UPDATE_MSG+="\n⬆️ $NAME updated from $CURRENT_VERSION to $LATEST_TAG"
  else
    log "$COLOR_GREEN" "✔️ $NAME is already up to date ($CURRENT_VERSION)"
  fi
  log "$COLOR_BLUE" "----------------------------"
done

# Commit and push changes if updated
if [[ $UPDATED -eq 1 ]]; then
  if [[ -z "$AUTH_REPO_URL" ]]; then
    log "$COLOR_YELLOW" "⚠️ Repository URL not configured, skipping git push."
  else
    git config --global user.email "updater@local"
    git config --global user.name "Addon Updater"
    git add .
    git commit -m "Update add-ons versions [ci skip]" || true
    git push "$AUTH_REPO_URL" HEAD || log "$COLOR_RED" "❌ Git push failed"
  fi
  send_notification "📦 Add-ons updated:$UPDATE_MSG"
else
  log "$COLOR_GREEN" "✅ No updates needed."
fi

# Cron schedule handling from config
CRON_SCHEDULE=$(jq -r '.cron_schedule // empty' "$CONFIG_PATH")
if [[ -z "$CRON_SCHEDULE" ]]; then
  log "$COLOR_YELLOW" "⚠️ Cron schedule not configured, exiting after this run."
  exit 0
fi

# Run cron schedule loop
log "$COLOR_BLUE" "⏳ Starting cron schedule: $CRON_SCHEDULE"
while true; do
  sleep 1
  if date +'%M %H %d %m %w' | grep -qE "$(echo "$CRON_SCHEDULE" | sed 's/ /|/g')"; then
    # Run update (reexec script)
    exec "$0"
  fi
done
