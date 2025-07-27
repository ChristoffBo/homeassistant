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

notify() {
  local message="$1"
  local slug="$2"
  
  # Load notification config
  local method=$(jq -r '.notifier.method // empty' "$CONFIG_PATH")
  
  case "$method" in
    gotify)
      local url=$(jq -r '.notifier.gotify.url' "$CONFIG_PATH")
      local token=$(jq -r '.notifier.gotify.token' "$CONFIG_PATH")
      if [[ -z "$url" || -z "$token" ]]; then
        log "$COLOR_YELLOW" "⚠️ Gotify notifier configured but missing url or token."
        return
      fi
      curl -s -X POST "$url/message?token=$token" -F "title=Addon Updated: $slug" -F "message=$message" >/dev/null 2>&1
      log "$COLOR_GREEN" "🔔 Notification sent via Gotify: $message"
      ;;
    mailrise)
      # Implement Mailrise notification if needed
      log "$COLOR_YELLOW" "⚠️ Mailrise notifier not implemented."
      ;;
    appirs)
      # Implement Appirs notification if needed
      log "$COLOR_YELLOW" "⚠️ Appirs notifier not implemented."
      ;;
    *)
      log "$COLOR_YELLOW" "⚠️ Notification method not configured or missing credentials."
      ;;
  esac
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

# Fetch tags from Docker Hub - only clean tags, exclude 'latest' or date strings.
get_latest_docker_tag_dockerhub() {
  local image="$1"
  local repo="${image%%:*}"
  # For images like 'library/nginx' or 'user/image'
  local namespace="library"
  local repo_name="$repo"

  if [[ "$repo" == *"/"* ]]; then
    namespace="${repo%%/*}"
    repo_name="${repo#*/}"
  fi

  local tags=$(curl -s "https://registry.hub.docker.com/v2/repositories/$namespace/$repo_name/tags/?page_size=100" | jq -r '.results[].name' 2>/dev/null)

  if [ -z "$tags" ]; then
    log "$COLOR_YELLOW" "⚠️ No tags found for Docker Hub image $image"
    echo ""
    return
  fi

  # Filter out 'latest' and any tags that don't look like version numbers
  # Keep tags matching version pattern: digits, dots, dashes (e.g., 1.2.3, v1.0, 2-rc)
  local valid_tags=$(echo "$tags" | grep -E '^[v]?[0-9]+([.-][0-9a-z]+)*$' | sort -V)

  if [ -z "$valid_tags" ]; then
    log "$COLOR_YELLOW" "⚠️ No valid tags found for Docker Hub image $image"
    echo ""
    return
  fi

  echo "$valid_tags" | tail -n1
}

# TODO: Implement similar functions to fetch from linuxserver.io and github if dockerhub empty
get_latest_docker_tag_linuxserver() {
  # Placeholder to extend: for now just return empty
  echo ""
}

get_latest_docker_tag_github() {
  # Placeholder to extend: for now just return empty
  echo ""
}

get_latest_docker_tag() {
  local image="$1"
  local tag=""

  tag=$(get_latest_docker_tag_dockerhub "$image")

  if [ -z "$tag" ]; then
    tag=$(get_latest_docker_tag_linuxserver "$image")
  fi

  if [ -z "$tag" ]; then
    tag=$(get_latest_docker_tag_github "$image")
  fi

  echo "$tag"
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
    return
  fi

  # Fix invalid version field in build.json if present
  if [ -f "$build_file" ]; then
    # Remove "version" field from build.json if it exists (invalid here)
    if jq -e '.version' "$build_file" >/dev/null 2>&1; then
      jq 'del(.version)' "$build_file" > "$build_file.tmp" && mv "$build_file.tmp" "$build_file"
      log "$COLOR_YELLOW" "⚠️ Removed invalid version field from build.json ($build_file)"
    fi
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
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
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

    jq --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    NEW_ENTRY="\
v$latest_version ($(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M'))
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

    notify "Updated $slug from $current_version to $latest_version" "$slug"

  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local any_updates=0

  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      update_addon_if_needed "$addon_path"
      any_updates=1
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
