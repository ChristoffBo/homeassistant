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

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

# Notifier config from options.json
NOTIFY_GOTIFY_URL=$(jq -r '.notify.gotify_url // empty' "$CONFIG_PATH")
NOTIFY_MAILRISE_URL=$(jq -r '.notify.mailrise_url // empty' "$CONFIG_PATH")
NOTIFY_APPRISE_URL=$(jq -r '.notify.apprise_url // empty' "$CONFIG_PATH")

notify() {
  local message="$1"

  if [ -n "$NOTIFY_GOTIFY_URL" ]; then
    curl -s -X POST -H "Content-Type: application/json" -d "{\"message\":\"$message\",\"title\":\"Addon Updater\"}" "$NOTIFY_GOTIFY_URL" >/dev/null 2>&1
  fi
  if [ -n "$NOTIFY_MAILRISE_URL" ]; then
    curl -s -X POST -H "Content-Type: application/json" -d "{\"text\":\"$message\"}" "$NOTIFY_MAILRISE_URL" >/dev/null 2>&1
  fi
  if [ -n "$NOTIFY_APPRISE_URL" ]; then
    curl -s -X POST -H "Content-Type: application/json" -d "{\"message\":\"$message\"}" "$NOTIFY_APPRISE_URL" >/dev/null 2>&1
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

get_latest_docker_tag() {
  local image="$1"

  # Extract repo and image name
  local repo image_name tag
  tag=""

  # Parse image repo and tag if present
  if [[ "$image" == *":"* ]]; then
    repo="${image%%:*}"
    tag="${image#*:}"
  else
    repo="$image"
  fi

  # Try DockerHub API first
  if [[ ! "$repo" =~ ^(ghcr.io|linuxserver.io) ]]; then
    local dockerhub_tags_url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&page=1&ordering=last_updated"
    local latest_tag
    latest_tag=$(curl -s "$dockerhub_tags_url" | jq -r '.results[0].name' 2>/dev/null)
    if [ -n "$latest_tag" ] && [ "$latest_tag" != "null" ]; then
      echo "$latest_tag"
      return
    fi
  fi

  # Try LinuxServer.io tags (simplified)
  if [[ "$repo" =~ ^linuxserver/ ]]; then
    local ls_tag_url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=1&page=1&ordering=last_updated"
    local ls_tag
    ls_tag=$(curl -s "$ls_tag_url" | jq -r '.results[0].name' 2>/dev/null)
    if [ -n "$ls_tag" ] && [ "$ls_tag" != "null" ]; then
      echo "$ls_tag"
      return
    fi
  fi

  # Try GitHub Packages (ghcr.io) — Placeholder, real logic depends on repo setup
  if [[ "$repo" =~ ^ghcr.io/ ]]; then
    # TODO: implement GitHub API call if needed
    echo "latest"
    return
  fi

  echo "latest"
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

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return 0
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
    return 0
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ' | tr -d '"')
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ] || [ "$latest_version" == "null" ]; then
    latest_version="latest"
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  local source_url
  source_url=$(get_docker_source_url "$image")

  if [ ! -f "$changelog_file" ]; then
    {
      echo "CHANGELOG for $slug"
      echo "==================="
      echo
      echo "Initial version: $current_version"
      echo "Docker Image source: $source_url"
      echo
    } > "$changelog_file"
    log "$COLOR_YELLOW" "🆕 Created new CHANGELOG.md for $slug with current tag $current_version and source URL"
  fi

  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file" 2>/dev/null)
  fi
  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update config.json version
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then mv "$config_file.tmp" "$config_file"; fi

    # Update updater.json
    jq --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt | .slug = "'$slug'" | .image = "'$image'"' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    # Prepend changelog entry
    local NEW_ENTRY="\
v$latest_version ($(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M'))
    Update from version $current_version to $latest_version (image: $image)

"
    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    # Notify only on updates
    notify "Addon $slug updated from $current_version to $latest_version"

    return 1 # Indicates an update happened
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
    return 0
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updates_happened=0

  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      if update_addon_if_needed "$addon_path"; then
        updates_happened=1
      fi
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$updates_happened" -eq 1 ] && [ "$(git status --porcelain)" ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
      notify "Git push successful after addon updates."
    else
      log "$COLOR_RED" "❌ Git push failed."
      notify "Git push failed after addon updates!"
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

log "$COLOR_PURPLE" "🔮 Starting Add-on Updater..."
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running update check now..."
perform_update_check
log "$COLOR_GREEN" "😴 Updater run finished."

exit 0
