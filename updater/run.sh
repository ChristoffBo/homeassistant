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

NOTIFIER_GOTIFY=$(jq -r '.notifiers.gotify // empty' "$CONFIG_PATH")
NOTIFIER_MAILRISE=$(jq -r '.notifiers.mailrise // empty' "$CONFIG_PATH")
NOTIFIER_APPRIS=$(jq -r '.notifiers.appris // empty' "$CONFIG_PATH")

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

send_notification() {
  local title="$1"
  local message="$2"

  if [ -n "$NOTIFIER_GOTIFY" ]; then
    curl -s -X POST "$NOTIFIER_GOTIFY/message" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"message\":\"$message\"}" > /dev/null 2>&1
  fi

  if [ -n "$NOTIFIER_MAILRISE" ]; then
    curl -s -X POST "$NOTIFIER_MAILRISE" \
      -H "Content-Type: application/json" \
      -d "{\"subject\":\"$title\",\"text\":\"$message\"}" > /dev/null 2>&1
  fi

  if [ -n "$NOTIFIER_APPRIS" ]; then
    curl -s -X POST "$NOTIFIER_APPRIS" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"body\":\"$message\"}" > /dev/null 2>&1
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

filter_valid_tags() {
  # Filter tags: only digits, dots, optional dash/letters allowed
  grep -E '^[0-9]+(\.[0-9]+)*(-[0-9A-Za-z]+)?$'
}

get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"

  # LinuxServer tags via lscr.io API
  if [[ "$image_no_tag" =~ ^lscr.io/linuxserver/([^/]+)$ ]]; then
    local repo="${BASH_REMATCH[1]}"
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

  # DockerHub official registry
  local repo=""
  if [[ "$image" =~ ^([^/]+/[^@:]+) ]]; then
    repo="${BASH_REMATCH[1]}"
  else
    repo="$image"
  fi

  local token
  token=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${repo}:pull" 2>/dev/null | jq -r '.token // empty')

  if [ -n "$token" ]; then
    local tags_json
    tags_json=$(curl -s -H "Authorization: Bearer $token" "https://registry.hub.docker.com/v2/repositories/${repo}/tags?page_size=50" 2>/dev/null)
    local tags
    tags=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null | filter_valid_tags | sort -V)
    if [ -n "$tags" ]; then
      echo "$tags" | tail -n1
      return
    fi
  fi

  # linuxserver.io DockerHub fallback
  if [[ "$repo" =~ ^linuxserver/ ]]; then
    local tags_json
    tags_json=$(curl -s "https://hub.linuxserver.io/v2/repositories/$repo/tags?page_size=50" 2>/dev/null)
    local tags
    tags=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null | filter_valid_tags | sort -V)
    if [ -n "$tags" ]; then
      echo "$tags" | tail -n1
      return
    fi
  fi

  # GHCR fallback (basic)
  if [[ "$image" =~ ^ghcr.io/ ]]; then
    local repo_name=${image#ghcr.io/}
    local tags_json
    tags_json=$(curl -s "https://ghcr.io/v2/${repo_name}/tags/list" 2>/dev/null)
    local tags
    tags=$(echo "$tags_json" | jq -r '.tags[]?' 2>/dev/null | filter_valid_tags | sort -V)
    if [ -n "$tags" ]; then
      echo "$tags" | tail -n1
      return
    fi
  fi

  echo ""
}

sanitize_version() {
  local ver="$1"
  ver="${ver//\"/}"
  ver="${ver#version-}"
  ver="${ver#v}"
  ver="$(echo "$ver" | xargs)"  # trim whitespace
  echo "$ver"
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"
  local slug

  # Validate presence of at least one descriptor file
  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json and build.json, skipping."
    return
  fi

  # Determine Docker image from build.json (multi-arch) or config.json
  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    case "$arch" in
      x86_64) arch="amd64" ;;
    esac
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file" 2>/dev/null)
  fi
  if [ -z "$image" ] || [ "$image" == "null" ]; then
    if [ -f "$config_file" ]; then
      image=$(jq -r '.image // empty' "$config_file" 2>/dev/null)
    fi
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' has no Docker image defined, skipping."
    return
  fi

  # Slug from config or folder name
  if [ -f "$config_file" ]; then
    slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  fi
  if [ -z "$slug" ]; then
    slug=$(basename "$addon_path")
  fi

  # Get current version from config.json or build.json (fallback)
  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null)
  elif [ -f "$build_file" ]; then
    current_version=$(jq -r '.version // empty' "$build_file" 2>/dev/null)
  fi
  current_version=$(sanitize_version "$current_version")

  # Get upstream_version & last_update from updater.json if exists
  local upstream_version=""
  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file" 2>/dev/null)
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file" 2>/dev/null)
  fi
  upstream_version=$(sanitize_version "$upstream_version")

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"
  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")
  latest_version=$(sanitize_version "$latest_version")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "⚠️ Could not determine latest tag for $slug, skipping update."
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  # If latest_version differs from current_version, update config and changelog
  if [ "$latest_version" != "$current_version" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update config.json version
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
      mv "$config_file.tmp" "$config_file"
    fi

    # Update build.json version if present and if version field exists (clean invalid version)
    if [ -f "$build_file" ]; then
      # Remove invalid version field if it's not a proper tag
      local build_version
      build_version=$(jq -r '.version // empty' "$build_file" 2>/dev/null)
      if [ -n "$build_version" ] && ! echo "$build_version" | grep -Eq '^[0-9]+(\.[0-9]+)*(-[0-9A-Za-z]+)?$'; then
        jq 'del(.version)' "$build_file" > "$build_file.tmp" 2>/dev/null || true
        mv "$build_file.tmp" "$build_file"
        log "$COLOR_YELLOW" "⚠️ Removed invalid version field from build.json ($build_file)"
      fi
    fi

    # Update updater.json
    jq --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt | .slug = $slug | .image = $image' \
      "$updater_file" 2>/dev/null > "$updater_file.tmp" || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
    mv "$updater_file.tmp" "$updater_file"

    # Create or prepend CHANGELOG.md
    if [ ! -f "$changelog_file" ]; then
      {
        echo "CHANGELOG for $slug"
        echo "==================="
        echo
        echo "Initial version: $current_version"
        echo
      } > "$changelog_file"
      log "$COLOR_YELLOW" "🆕 Created new CHANGELOG.md for $slug"
    fi

    local new_entry="v$latest_version ($(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M'))\n    Updated from version $current_version to $latest_version (image: $image)\n"

    { 
      head -n 2 "$changelog_file"
      echo -e "$new_entry"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    # Send notification
    send_notification "Addon Update: $slug" "Updated from $current_version to $latest_version"

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
    if git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1; then
      if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
        log "$COLOR_GREEN" "✅ Git push successful."
      else
        log "$COLOR_RED" "❌ Git push failed."
      fi
    else
      log "$COLOR_RED" "❌ Git commit failed."
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."
log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_GREEN" "📅 Scheduled cron: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check
log "$COLOR_GREEN" "⏳ Waiting for cron to trigger..."

# Sleep loop just to keep container alive; actual schedule is handled by Home Assistant addon cron
while sleep 60; do :; done
