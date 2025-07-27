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

# Read config
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

# Notifier configs (optional)
NOTIFIER_GOTIFY_URL=$(jq -r '.notifiers.gotify.url // empty' "$CONFIG_PATH")
NOTIFIER_MAILRISE_URL=$(jq -r '.notifiers.mailrise.url // empty' "$CONFIG_PATH")
NOTIFIER_APPRISE_URL=$(jq -r '.notifiers.apprise.url // empty' "$CONFIG_PATH")

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

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
      exit 1
    fi
  fi
}

send_notifier_message() {
  local title="$1"
  local message="$2"

  # Gotify
  if [ -n "$NOTIFIER_GOTIFY_URL" ]; then
    curl -s -X POST -H "Content-Type: application/json" -d "{\"title\":\"$title\",\"message\":\"$message\"}" "$NOTIFIER_GOTIFY_URL" >/dev/null 2>&1 || \
      log "$COLOR_YELLOW" "⚠️ Gotify notification failed"
  fi

  # Mailrise
  if [ -n "$NOTIFIER_MAILRISE_URL" ]; then
    curl -s -X POST -H "Content-Type: application/json" -d "{\"text\":\"$title\n$message\"}" "$NOTIFIER_MAILRISE_URL" >/dev/null 2>&1 || \
      log "$COLOR_YELLOW" "⚠️ Mailrise notification failed"
  fi

  # Apprise
  if [ -n "$NOTIFIER_APPRISE_URL" ]; then
    curl -s -X POST -H "Content-Type: application/json" -d "{\"title\":\"$title\",\"body\":\"$message\"}" "$NOTIFIER_APPRISE_URL" >/dev/null 2>&1 || \
      log "$COLOR_YELLOW" "⚠️ Apprise notification failed"
  fi
}

get_latest_docker_tag() {
  local image="$1"

  # Try DockerHub
  token=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${image}:pull" | jq -r '.token')
  if [ -n "$token" ] && [ "$token" != "null" ]; then
    tag=$(curl -s -H "Authorization: Bearer $token" "https://registry.hub.docker.com/v2/repositories/${image}/tags?page_size=50" | jq -r '.results[].name' | grep -v latest | sort -V | tail -n1)
    if [ -n "$tag" ]; then
      echo "$tag"
      return
    fi
  fi

  # Fallback linuxserver.io tags
  if [[ "$image" =~ ^linuxserver/ ]]; then
    tags=$(curl -s "https://hub.linuxserver.io/v2/repositories/$image/tags?page_size=50" | jq -r '.results[].name' 2>/dev/null)
    if [ -n "$tags" ]; then
      echo "$tags" | grep -v latest | sort -V | tail -n1
      return
    fi
  fi

  # Fallback GitHub container registry (very basic)
  if [[ "$image" =~ ^ghcr.io/ ]]; then
    repo_name=${image#ghcr.io/}
    tags=$(curl -s "https://ghcr.io/v2/${repo_name}/tags/list" | jq -r '.tags[]' 2>/dev/null)
    if [ -n "$tags" ]; then
      echo "$tags" | grep -v latest | sort -V | tail -n1
      return
    fi
  fi

  # Final fallback: return 'latest'
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

  # Skip if no config or build or updater file
  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ] && [ ! -f "$updater_file" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing config.json, build.json and updater.json, skipping."
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
    current_version=$(jq -r '.version // empty' "$config_file" 2>/dev/null | tr -d '\n\r ')
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

  # Create CHANGELOG.md if missing
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

    # Update version in config.json
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true
    if [ -f "$config_file.tmp" ]; then mv "$config_file.tmp" "$config_file"; fi

    # Update updater.json or create new
    jq --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    # Prepend changelog entry
    NEW_ENTRY="\
v$latest_version ($(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M'))
    Update from version $current_version to $latest_version (image: $image)

"
    {
      head -n 2 "$changelog_file"
      echo "$NEW_ENTRY"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    # Return 0 means updated
    echo "$slug|$current_version|$latest_version|$changelog_file|$updater_file"
    return 0
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
    return 1
  fi
}

perform_update_check() {
  clone_or_update_repo

  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updated_any=0
  local notify_msgs=""

  for addon_path in "$REPO_DIR"/*/; do
    if [ -d "$addon_path" ]; then
      # Update only addons with any of the config files
      if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
        update_result=$(update_addon_if_needed "$addon_path") || true
        if [ -n "$update_result" ]; then
          updated_any=1
          IFS="|" read -r slug old_ver new_ver changelog_file updater_file <<< "$update_result"
          notify_msgs+="Addon: $slug\nUpdated from $old_ver to $new_ver\n"
        fi
      else
        log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
      fi
    fi
  done

  if [ "$updated_any" -eq 1 ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."

      # Send notification
      send_notifier_message "Home Assistant Addons Updated" "$notify_msgs"
    else
      log "$COLOR_RED" "❌ Git push failed."
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

# Wait infinitely for cron to trigger (Home Assistant will run this script per cron)
while sleep 60; do :; done
