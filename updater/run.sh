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

: > "$LOG_FILE"

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

notify() {
  local message="$1"
  local title="${2:-Home Assistant Add-on Updater}"

  local gotify_url
  local gotify_token
  local mailrise_url
  local mailrise_token
  local apprise_url

  gotify_url=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
  gotify_token=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
  mailrise_url=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
  mailrise_token=$(jq -r '.mailrise.token // empty' "$CONFIG_PATH")
  apprise_url=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")

  if [ -n "$gotify_url" ] && [ -n "$gotify_token" ]; then
    curl -s -X POST "$gotify_url/message?token=$gotify_token" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$title\",\"message\":\"$message\",\"priority\":5}" > /dev/null 2>&1
  fi

  if [ -n "$mailrise_url" ] && [ -n "$mailrise_token" ]; then
    curl -s -X POST "$mailrise_url/api/notification" \
      -H "Authorization: Bearer $mailrise_token" \
      -H "Content-Type: application/json" \
      -d "{\"message\":\"$message\",\"title\":\"$title\"}" > /dev/null 2>&1
  fi

  if [ -n "$apprise_url" ]; then
    curl -s -X POST "$apprise_url" \
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
      notify "Repository cloned successfully." "Add-on Updater"
    else
      log "$COLOR_RED" "❌ Failed to clone repository."
      notify "Failed to clone repository." "Add-on Updater ERROR"
      exit 1
    fi
  else
    log "$COLOR_PURPLE" "🔄 Pulling latest changes from GitHub..."
    cd "$REPO_DIR"
    if git pull "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git pull successful."
      notify "Git pull successful." "Add-on Updater"
    else
      log "$COLOR_RED" "❌ Git pull failed."
      notify "Git pull failed." "Add-on Updater ERROR"
    fi
  fi
}

# Function to fetch the latest Docker tag (excluding 'latest') from Docker Hub API
get_latest_docker_tag() {
  local image="$1"
  local repository tag_url tags_json latest_tag

  # Remove tag suffix if exists
  repository="${image%%:*}"

  # Handle ghcr.io URLs (use GitHub API)
  if [[ "$repository" == ghcr.io/* ]]; then
    # Example: ghcr.io/org/image:tag
    # For simplicity, fallback to "latest"
    echo "latest"
    return
  fi

  # Remove registry domain if present
  if [[ "$repository" == */*/* ]]; then
    # e.g., lscr.io/linuxserver/heimdall -> linuxserver/heimdall
    repository="${repository#*/}"
  fi

  tag_url="https://registry.hub.docker.com/v2/repositories/${repository}/tags?page_size=100"

  tags_json=$(curl -s "$tag_url")

  # Extract tag names, filter out 'latest', sort and get the latest semantic version or latest by date
  latest_tag=$(echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | sort -V | tail -n1)

  if [ -z "$latest_tag" ]; then
    echo "latest"
  else
    echo "$latest_tag"
  fi
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

send_update_notifications() {
  local slug="$1"
  local old_version="$2"
  local new_version="$3"

  local message="Updated $slug from $old_version to $new_version"
  local title="Add-on Updater"

  notify "$message" "$title"
}

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  # Try to find image from build.json or config.json
  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    [ "$arch" == "x86_64" ] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from' "$build_file" 2>/dev/null)
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing image field, skipping."
    return
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local current_version=""
  if [ -f "$config_file" ]; then
    current_version=$(jq -r '.version // empty' "$config_file" | tr -d '\n\r ')
  fi

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")
  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  local source_url
  source_url=$(get_docker_source_url "$image")
  local timestamp
  timestamp=$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')

  if [ ! -f "$changelog_file" ] || ! grep -q "^CHANGELOG for $slug" "$changelog_file"; then
    {
      echo "CHANGELOG for $slug"
      echo "==================="
      echo
      echo "Initial version: $current_version"
      echo "Docker Image source: $source_url"
      echo
    } > "$changelog_file"
    log "$COLOR_YELLOW" "🆕 Created or fixed CHANGELOG.md for $slug"
  fi

  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file")
  fi

  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  # Check if we need to update
  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update config.json version
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
    fi

    # Update updater.json
    if [ -f "$updater_file" ] && jq -e . "$updater_file" >/dev/null 2>&1; then
      jq --arg v "$latest_version" --arg dt "$timestamp" --arg img "$image" --arg slug "$slug" \
        '.upstream_version = $v | .last_update = $dt | .image = $img | .slug = $slug' "$updater_file" > "$updater_file.tmp"
      mv "$updater_file.tmp" "$updater_file"
      log "$COLOR_GREEN" "✅ Updated updater.json for $slug"
    else
      jq -n --arg slug "$slug" --arg img "$image" --arg v "$latest_version" --arg dt "$timestamp" \
        '{slug: $slug, image: $img, upstream_version: $v, last_update: $dt}' > "$updater_file"
      log "$COLOR_GREEN" "✅ Created updater.json for $slug"
    fi

    # Update changelog
    local new_entry="v$latest_version ($timestamp)
    Update from version $current_version to $latest_version (image: $image)

"
    {
      head -n 2 "$changelog_file"
      echo "$new_entry"
      tail -n +3 "$changelog_file"
    } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    # Notify only if updated
    send_update_notifications "$slug" "$current_version" "$latest_version"

    # Return success for git commit
    return 0
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
    return 1
  fi

  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo
  cd "$REPO_DIR"
  git config user.email "updater@local"
  git config user.name "HomeAssistant Updater"

  local updates_found=0

  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      if update_addon_if_needed "$addon_path"; then
        updates_found=1
      fi
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$updates_found" -eq 1 ]; then
    git add .
    git commit -m "⬆️ Update addon versions" >> "$LOG_FILE" 2>&1 || true
    if git push "$GIT_AUTH_REPO" main >> "$LOG_FILE" 2>&1; then
      log "$COLOR_GREEN" "✅ Git push successful."
      notify "Git push successful with updates." "Add-on Updater"
    else
      log "$COLOR_RED" "❌ Git push failed."
      notify "Git push failed!" "Add-on Updater ERROR"
    fi
  else
    log "$COLOR_BLUE" "📦 No add-on updates found; no commit necessary."
  fi
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  notify "ERROR: Config file $CONFIG_PATH not found!" "Add-on Updater ERROR"
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

log "$COLOR_PURPLE" "🔮 Add-on Updater started"
log "$COLOR_BLUE" "📅 Cron schedule: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check..."

perform_update_check

log "$COLOR_GREEN" "⏳ Waiting for next scheduled run..."

while true; do
  next_run=$(env TZ="$TIMEZONE" date -d "$(crontab -l | grep -F "$CHECK_CRON" | head -n1)" '+%H:%M' 2>/dev/null)
  if [ -z "$next_run" ]; then
    # fallback if no valid cron found, sleep 1 hour
    sleep 3600
  else
    now=$(env TZ="$TIMEZONE" date +%s)
    run_time=$(env TZ="$TIMEZONE" date -d "$next_run" +%s)
    if [ $run_time -le $now ]; then
      run_time=$((run_time + 86400))
    fi
    sleep_time=$((run_time - now))
    log "$COLOR_BLUE" "🕒 Next run at $next_run ($sleep_time seconds)"
    sleep $sleep_time
  fi

  log "$COLOR_GREEN" "🏃 Running scheduled update check..."
  perform_update_check
done
