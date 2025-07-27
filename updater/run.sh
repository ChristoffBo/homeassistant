#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ

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
  local type=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
  local url=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
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

get_image_and_version() {
  local dir="$1"
  local image=""
  local version=""

  for file in config.json build.json updater.json; do
    if [[ -f "$REPO_DIR/$dir/$file" ]]; then
      image_candidate=$(jq -r '.image // empty' "$REPO_DIR/$dir/$file")
      version_candidate=$(jq -r '.version // empty' "$REPO_DIR/$dir/$file")
      if [[ -n "$image_candidate" ]]; then
        image="$image_candidate"
      fi
      if [[ -n "$version_candidate" ]]; then
        version="$version_candidate"
      fi
      if [[ -n "$image" && -n "$version" ]]; then
        break
      fi
    fi
  done

  echo "$image" "$version"
}

clean_tag() {
  local tag="$1"
  echo "$tag" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//'
}

fetch_latest_tag() {
  local repo="$1"
  local api_url="https://hub.docker.com/v2/repositories/$repo/tags?page_size=100"
  log "$COLOR_BLUE" "🔍 Fetching tags from Docker Hub API: $api_url"

  local tags_json
  tags_json=$(curl -sS "$api_url")

  if ! echo "$tags_json" | jq -e '.results' > /dev/null 2>&1; then
    echo ""
    return 1
  fi

  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v -E 'latest|rc' | sort -Vr | head -n1)

  echo "$latest_tag"
}

UPDATED=0
NOTIFY_MSG=""

cd "$REPO_DIR" || { log "$COLOR_RED" "❌ Could not enter repository directory"; exit 1; }

for addon_dir in */ ; do
  if [[ ! -f "$REPO_DIR/$addon_dir/config.json" ]]; then
    continue
  fi

  NAME=$(jq -r '.name // empty' "$REPO_DIR/$addon_dir/config.json")
  [[ -z "$NAME" ]] && NAME="$addon_dir"

  read -r IMAGE CURRENT_VERSION < <(get_image_and_version "$addon_dir")

  if [[ -z "$IMAGE" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$NAME' has no Docker image defined, skipping."
    continue
  fi

  REPO="${IMAGE%:*}"
  TAG="${IMAGE##*:}"

  log "$COLOR_PURPLE" "\n🧩 Addon: $NAME"
  log "$COLOR_BLUE" "🔢 Current version: $CURRENT_VERSION"
  log "$COLOR_BLUE" "📦 Image: $IMAGE"

  if echo "$IMAGE" | jq -e . >/dev/null 2>&1; then
    ARCH=$(jq -r '.arch // "amd64"' "$CONFIG_PATH")
    IMAGE=$(echo "$IMAGE" | jq -r --arg arch "$ARCH" '.[$arch] // empty')
    if [[ -z "$IMAGE" ]]; then
      log "$COLOR_RED" "❌ No image found for architecture '$ARCH' in $NAME, skipping."
      continue
    fi
    REPO="${IMAGE%:*}"
    TAG="${IMAGE##*:}"
    log "$COLOR_BLUE" "📦 Architecture-specific Image: $IMAGE"
  fi

  if [[ "$TAG" == "latest" || "$TAG" == *"latest" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$NAME' uses 'latest' tag; will try to find latest specific version tag."

    CLEAN_REPO="$REPO"
    if [[ "$REPO" == lscr.io/linuxserver/* ]]; then
      CLEAN_REPO="${REPO#lscr.io/}"
      CLEAN_REPO="linuxserver/$CLEAN_REPO"
    elif [[ "$REPO" == docker.io/* ]]; then
      CLEAN_REPO="${REPO#docker.io/}"
    fi

    LATEST_TAG=$(fetch_latest_tag "$CLEAN_REPO")

    if [[ -z "$LATEST_TAG" ]]; then
      log "$COLOR_RED" "❌ Could not fetch tags for $REPO"
      continue
    fi
  else
    LATEST_TAG=$(clean_tag "$TAG")
  fi

  log "$COLOR_GREEN" "🚀 Latest version: $LATEST_TAG"
  log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

  if [[ "$CURRENT_VERSION" != "$LATEST_TAG" ]]; then
    log "$COLOR_YELLOW" "⬆️  Updating $NAME from $CURRENT_VERSION to $LATEST_TAG"

    for file in build.json updater.json config.json; do
      if [[ -f "$REPO_DIR/$addon_dir/$file" ]]; then
        jq --arg ver "$LATEST_TAG" '.version = $ver' "$REPO_DIR/$addon_dir/$file" > tmp.$$.json && mv tmp.$$.json "$REPO_DIR/$addon_dir/$file"
      fi
    done

    CHANGELOG="$REPO_DIR/$addon_dir/CHANGELOG.md"
    if [[ ! -f "$CHANGELOG" ]]; then
      echo "# Changelog" > "$CHANGELOG"
    fi
    echo -e "\n## $LATEST_TAG - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$TAG\` to \`$LATEST_TAG\`" >> "$CHANGELOG"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $NAME"

    UPDATED=1
    NOTIFY_MSG+="⬆️ Updated $NAME from $CURRENT_VERSION to $LATEST_TAG\n"
  else
    log "$COLOR_GREEN" "✔️ $NAME is already up to date ($CURRENT_VERSION)"
  fi

  log "$COLOR_BLUE" "----------------------------"
done

GIT_URL=$(jq -r '.git.url // empty' "$CONFIG_PATH")
GIT_USER=$(jq -r '.git.username // empty' "$CONFIG_PATH")
GIT_TOKEN=$(jq -r '.git.token // empty' "$CONFIG_PATH")

if [[ $UPDATED -eq 1 ]]; then
  if [[ -z "$GIT_URL" || -z "$GIT_USER" || -z "$GIT_TOKEN" ]]; then
    log "$COLOR_YELLOW" "⚠️ Git credentials incomplete; skipping git push."
  else
    GIT_URL="${GIT_URL%.git}"
    AUTH_URL=$(echo "$GIT_URL" | sed -E "s#https://#https://$GIT_USER:$GIT_TOKEN@#")

    git config --global user.email "updater@local"
    git config --global user.name "Addon Updater Bot"

    git add .
    git commit -m "Updated addon versions $(date '+%Y-%m-%d %H:%M:%S')" || true
    git push "$AUTH_URL" HEAD || {
      log "$COLOR_RED" "❌ Git push failed"
    }
  fi

  send_notification "🟢 Addons updated:\n$NOTIFY_MSG"
else
  log "$COLOR_GREEN" "✅ No updates needed."
fi

CRON_SCHEDULE=$(jq -r '.cron // empty' "$CONFIG_PATH")
if [[ -n "$CRON_SCHEDULE" ]]; then
  log "$COLOR_BLUE" "⏰ Sleeping until next scheduled run: $CRON_SCHEDULE"
  echo "$CRON_SCHEDULE /run.sh" > /etc/crontabs/root
  crond -f -d 8
else
  log "$COLOR_YELLOW" "⚠️ Cron schedule not found; script will exit."
fi
