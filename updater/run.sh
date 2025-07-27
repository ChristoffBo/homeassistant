#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

# Clear log file on startup
: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

NOTIFY_METHOD=$(jq -r '.notify_method // empty' "$CONFIG_PATH") # "gotify", "mailrise", "appirs" or empty
GOTIFY_URL=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
GOTIFY_TOKEN=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
MAILRISE_URL=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
MAILRISE_TOKEN=$(jq -r '.mailrise.token // empty' "$CONFIG_PATH")
APPIRS_URL=$(jq -r '.appirs.url // empty' "$CONFIG_PATH")
APPIRS_TOKEN=$(jq -r '.appirs.token // empty' "$CONFIG_PATH")

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

send_notification() {
  local title="$1"
  local message="$2"
  if [ "$NOTIFY_METHOD" = "gotify" ] && [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
    curl -s -X POST "$GOTIFY_URL/message" \
      -H "X-Gotify-Key: $GOTIFY_TOKEN" \
      -F "title=$title" \
      -F "message=$message" \
      -F "priority=5" >/dev/null 2>&1
    log "$COLOR_GREEN" "🔔 Notification sent via Gotify: $title"
  elif [ "$NOTIFY_METHOD" = "mailrise" ] && [ -n "$MAILRISE_URL" ] && [ -n "$MAILRISE_TOKEN" ]; then
    curl -s -X POST "$MAILRISE_URL/api/notification" \
      -H "Authorization: Bearer $MAILRISE_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"message\":\"$message\"}" >/dev/null 2>&1
    log "$COLOR_GREEN" "🔔 Notification sent via Mailrise: $title"
  elif [ "$NOTIFY_METHOD" = "appirs" ] && [ -n "$APPIRS_URL" ] && [ -n "$APPIRS_TOKEN" ]; then
    curl -s -X POST "$APPIRS_URL/api/notify" \
      -H "Authorization: Bearer $APPIRS_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"message\":\"$message\"}" >/dev/null 2>&1
    log "$COLOR_GREEN" "🔔 Notification sent via Appirs: $title"
  else
    log "$COLOR_YELLOW" "⚠️ Notification method not configured or missing credentials."
  fi
}

clone_or_update_repo() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
  if [ ! -d "$REPO_DIR" ]; then
    log "$COLOR_PURPLE" "📂 Cloning repository..."
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR" >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      exit 1
    fi
  else
    log "$COLOR_PURPLE" "🔄 Pulling latest changes from GitHub..."
    cd "$REPO_DIR"
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git pull successful."
    else
      log "$COLOR_RED" "❌ Git pull failed."
    fi
  fi
}

# Helper: filter out invalid tags (keep semantic version or date-like, skip 'latest' or empty)
filter_valid_tags() {
  grep -E '^[0-9]+(\.[0-9]+)*(-[a-zA-Z0-9._-]+)?$'
}

get_latest_docker_tag() {
  local image="$1"
  local base_image="${image%%:*}"

  # Strip arch suffix for linuxserver images
  if [[ "$base_image" =~ ^lscr.io/linuxserver/ ]]; then
    local repo="${base_image#lscr.io/linuxserver/}"
    local tags_json
    tags_json=$(curl -s "https://lscr.io/v2/linuxserver/${repo}/tags/list" 2>/dev/null)
    local tags
    tags=$(echo "$tags_json" | jq -r '.tags[]?' 2>/dev/null | filter_valid_tags | sort -V)
    if [ -n "$tags" ]; then
      echo "$tags" | tail -n1
      return
    else
      log "$COLOR_YELLOW" "⚠️ No valid tags found for lscr.io/linuxserver/$repo"
      echo ""
      return
    fi
  fi

  # Docker Hub token
  local token
  token=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${base_image}:pull" 2>/dev/null | jq -r '.token // empty')

  if [ -n "$token" ]; then
    local tags_json
    tags_json=$(curl -s -H "Authorization: Bearer $token" "https://registry.hub.docker.com/v2/repositories/${base_image}/tags?page_size=100" 2>/dev/null)
    local tags
    tags=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null | filter_valid_tags | sort -V)
    if [ -n "$tags" ]; then
      echo "$tags" | tail -n1
      return
    else
      log "$COLOR_YELLOW" "⚠️ No valid tags found for Docker Hub image $base_image"
      echo ""
      return
    fi
  fi

  log "$COLOR_YELLOW" "⚠️ Could not fetch tags for $image"
  echo ""
}

get_docker_source_url() {
  local image="$1"
  if [[ "$image" =~ ^linuxserver/ ]]; then
    echo "https://www.linuxserver.io/dockerhub/$image"
  elif [[ "$image" =~ ^ghcr.io/ ]]; then
    echo "https://github.com/orgs/linuxserver/packages/container/$image"
  else
    echo "https://hub.docker.com/r/$image"
  fi
}

fix_build_json_version_field() {
  local build_file="$1"
  # Remove invalid version field if it contains quotes or invalid JSON fragment
  if jq -e '.version | strings' "$build_file" >/dev/null 2>&1; then
    local ver
    ver=$(jq -r '.version' "$build_file")
    if [[ "$ver" == *'"'* ]] || [[ "$ver" == *'\n'* ]]; then
      jq 'del(.version)' "$build_file" > "$build_file.tmp" && mv "$build_file.tmp" "$build_file"
      log "$COLOR_YELLOW" "⚠️ Removed invalid version field from build.json ($build_file)"
    fi
  fi
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return
  fi

  if [ -f "$build_file" ]; then
    fix_build_json_version_field "$build_file"
  fi

  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
  fi

  local slug
  if [ -f "$config_file" ]; then
    slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  fi
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"
  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "⚠️ Could not determine latest tag for $slug, skipping update."
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  if [ "$latest_version" != "$current_version" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then mv "$config_file.tmp" "$config_file"; fi

    local dt
    dt=$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')

    if [ -f "$updater_file" ]; then
      jq --arg v "$latest_version" --arg dt "$dt" '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || true
      mv "$updater_file.tmp" "$updater_file"
    else
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$dt" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file"
    fi

    local NEW_ENTRY="v$latest_version ($dt)
    Update from version $current_version to $latest_version (image: $image)

"

    if [ ! -f "$changelog_file" ]; then
      {
        echo "CHANGELOG for $slug"
        echo "==================="
        echo
        echo "Initial version: $current_version"
        echo "Docker Image source: $(get_docker_source_url "$image")"
        echo
      } > "$changelog_file"
      log "$COLOR_YELLOW" "🆕 Created new CHANGELOG.md for $slug"
    fi

    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    send_notification "Addon Updated: $slug" "Updated from $current_version to $latest_version (image: $image)"
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR" || exit
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local any_updates=0

  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      if update_addon_if_needed "$addon_path"; then
        any_updates=1
      fi
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "❌ Git push failed."
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

log "$COLOR_PURPLE" "🔮 Starting Add-on Updater..."
log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check
log "$COLOR_GREEN" "⏳ Waiting for cron to trigger..."

while sleep 60; do :; done
