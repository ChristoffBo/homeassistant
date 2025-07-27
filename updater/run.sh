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

  local gotify_url=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
  local gotify_token=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
  local mailrise_url=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
  local mailrise_token=$(jq -r '.mailrise.token // empty' "$CONFIG_PATH")
  local apprise_url=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")

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

fetch_latest_dockerhub_tag() {
  local image="$1"
  local repo tag

  # Remove registry prefix and tag if any, e.g. "lscr.io/linuxserver/heimdall:amd64-latest" -> "linuxserver/heimdall"
  repo="${image#*/}"       # Remove registry host if exists
  repo="${repo%%:*}"      # Remove tag suffix

  # Special case if image uses ghcr.io or others, fallback to repo as is if empty
  if [ -z "$repo" ]; then
    repo="$image"
  fi

  tag=$(curl -s "https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100" | \
    jq -r '
      if (.results | type == "array") then
        .results[].name
        | select(. != "latest")
      else
        empty
      end
    ' | sort -V | tail -n1)

  if [ -z "$tag" ]; then
    log "$COLOR_YELLOW" "⚠️ No Docker tags found for $repo, falling back to 'latest'"
    tag="latest"
  fi

  echo "$tag"
}

fetch_latest_github_release() {
  local repo_url="$1"
  # Extract user/repo from full GitHub URL (https://github.com/user/repo)
  local repo_path
  repo_path=$(echo "$repo_url" | sed -E 's#https://github.com/([^/]+/[^/]+).*#\1#')

  curl -s "https://api.github.com/repos/$repo_path/releases/latest" | jq -r '.tag_name // empty'
}

fetch_latest_linuxserver_tag() {
  local image="$1"
  # For linuxserver.io, try GitHub repo or docker tags - simplistic fallback
  local ls_repo
  ls_repo=$(echo "$image" | sed -E 's#^lscr.io/linuxserver/([^:]+).*$#\1#')
  if [ -n "$ls_repo" ]; then
    fetch_latest_github_release "https://github.com/linuxserver/docker-$ls_repo"
  else
    echo "latest"
  fi
}

get_latest_tag() {
  local image="$1"
  local latest_tag=""

  if [[ "$image" =~ ^lscr.io/linuxserver/ ]]; then
    latest_tag=$(fetch_latest_linuxserver_tag "$image")
  elif [[ "$image" =~ ^ghcr.io/ ]]; then
    # For GitHub Container Registry, get latest release from GitHub
    # Extract repo from ghcr.io/org/repo/image:tag
    local gh_repo
    gh_repo=$(echo "$image" | sed -E 's#^ghcr.io/([^/]+/[^/:]+).*$#https://github.com/\1#')
    latest_tag=$(fetch_latest_github_release "$gh_repo")
  else
    # Default to Docker Hub
    latest_tag=$(fetch_latest_dockerhub_tag "$image")
  fi

  echo "$latest_tag"
}

update_addon_if_needed() {
  local addon_path="$1"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local updater_file="$addon_path/updater.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  # Determine image and slug
  local image=""
  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    [ "$arch" == "x86_64" ] && arch="amd64"
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from' "$build_file" 2>/dev/null)
  fi
  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi
  if [ -z "$image" ] && [ -f "$updater_file" ]; then
    image=$(jq -r '.image // empty' "$updater_file")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$(basename "$addon_path")' missing image field, skipping."
    return
  fi

  local slug=""
  if [ -f "$config_file" ]; then
    slug=$(jq -r '.slug // empty' "$config_file")
  fi
  if [ -z "$slug" ] && [ -f "$updater_file" ]; then
    slug=$(jq -r '.slug // empty' "$updater_file")
  fi
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
  latest_version=$(get_latest_tag "$image")
  [ -z "$latest_version" ] && latest_version="latest"

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  local timestamp
  timestamp=$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')

  # Fix or create CHANGELOG.md if missing or invalid
  if [ ! -f "$changelog_file" ] || ! grep -q "^CHANGELOG for $slug" "$changelog_file"; then
    {
      echo "CHANGELOG for $slug"
      echo "==================="
      echo
      echo "Initial version: $current_version"
      echo "Docker Image source: $image"
      echo
    } > "$changelog_file"
    log "$COLOR_YELLOW" "🆕 Created or fixed CHANGELOG.md for $slug"
  fi

  # Get last_update from updater.json or fallback
  local last_update="N/A"
  if [ -f "$updater_file" ]; then
    if jq -e . "$updater_file" >/dev/null 2>&1; then
      last_update=$(jq -r '.last_update // "N/A"' "$updater_file")
    else
      log "$COLOR_YELLOW" "⚠️ updater.json for $slug is invalid JSON"
    fi
  fi

  log "$COLOR_BLUE" "🕒 Last updated: $last_update"

  # Only update if version differs and latest is not empty or "latest"
  if [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "latest" ]; then
    log "$COLOR_GREEN" "⬆️  Updating $slug from $current_version to $latest_version"

    # Update config.json version
    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
    fi

    # Update updater.json (create if missing or invalid)
    if [ -f "$updater_file" ] && jq -e . "$updater_file" >/dev/null 2>&1; then
      jq --arg v "$latest_version" --arg dt "$timestamp" --arg img "$image" \
         '.upstream_version = $v | .last_update = $dt | .image = $img | .slug = $slug' "$updater_file" > "$updater_file.tmp"
    else
      jq -n --arg slug "$slug" --arg img "$image" --arg v "$latest_version" --arg dt "$timestamp" \
         '{slug: $slug, image: $img, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"
    fi
    mv "$updater_file.tmp" "$updater_file"
    log "$COLOR_GREEN" "✅ Updated updater.json for $slug"

    # Prepend changelog entry
    local new_entry="v$latest_version ($timestamp)
    Update from version $current_version to $latest_version (image: $image)

"
    { head -n 2 "$changelog_file"; echo "$new_entry"; tail -n +3 "$changelog_file"; } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"
    notify "Updated $slug from $current_version to $latest_version" "Add-on Updater"
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

  for addon_path in "$REPO_DIR"/*/; do
    if [ -f "$addon_path/config.json" ] || [ -f "$addon_path/build.json" ] || [ -f "$addon_path/updater.json" ]; then
      update_addon_if_needed "$addon_path"
    else
      log "$COLOR_YELLOW" "⚠️ Skipping folder $(basename "$addon_path") - no config.json, build.json or updater.json found"
    fi
  done

  if [ "$(git status --porcelain)" ]; then
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

get_next_cron_run() {
  local cron_expr="$1"
  local tz="$2"

  if ! command -v python3 >/dev/null 2>&1; then
    echo "N/A"
    return
  fi

  python3 - <<EOF
import sys
import croniter
from datetime import datetime
import pytz

cron_expr = sys.argv[1]
tz_name = sys.argv[2]
now = datetime.now(pytz.timezone(tz_name))
iter = croniter.croniter(cron_expr, now)
print(iter.get_next(datetime).strftime('%Y-%m-%d %H:%M:%S %Z'))
EOF
}

log "$COLOR_PURPLE" "🔮 Add-on Updater started"
log "$COLOR_GREEN" "📅 Cron schedule: $CHECK_CRON (Timezone: $TIMEZONE)"
log "$COLOR_GREEN" "🏃 Running initial update check..."
perform_update_check

next_run_time=$(get_next_cron_run "$CHECK_CRON" "$TIMEZONE")
log "$COLOR_GREEN" "⏳ Next scheduled run: $next_run_time"

while sleep 60; do
  current_time=$(date "+%M %H")
  # Compare current time to cron hour:min (support basic cron of "min hour * * *")
  cron_min=$(echo "$CHECK_CRON" | awk '{print $1}')
  cron_hour=$(echo "$CHECK_CRON" | awk '{print $2}')
  now_min=$(date '+%M')
  now_hour=$(date '+%H')

  if [ "$now_min" = "$cron_min" ] && [ "$now_hour" = "$cron_hour" ]; then
    log "$COLOR_PURPLE" "⏰ Cron triggered update check"
    perform_update_check
    next_run_time=$(get_next_cron_run "$CHECK_CRON" "$TIMEZONE")
    log "$COLOR_GREEN" "⏳ Next scheduled run: $next_run_time"
    sleep 60  # Avoid double run within the same minute
  fi
done
