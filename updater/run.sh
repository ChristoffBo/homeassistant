#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

# Get timezone from config or fallback
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
CRON_SCHEDULE=$(jq -r '.cron_schedule // "0 3 * * *"' "$CONFIG_PATH")

log() {
  local color="$1"
  shift
  local timestamp
  timestamp=$(date +"[%Y-%m-%d %H:%M:%S %Z]")
  echo -e "${timestamp} ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

calc_next_run() {
  local cron_expr="$1"
  local minute hour
  minute=$(echo "$cron_expr" | awk '{print $1}')
  hour=$(echo "$cron_expr" | awk '{print $2}')
  
  # Zero-pad minute and hour
  printf -v minute "%02d" "$minute"
  printf -v hour "%02d" "$hour"

  # Current time in hours and minutes
  local now_hour now_minute now_epoch next_epoch
  now_hour=$(date +"%H")
  now_minute=$(date +"%M")
  now_epoch=$(date +%s)

  if ((10#$hour > 10#$now_hour)) || { ((10#$hour == 10#$now_hour)) && ((10#$minute > 10#$now_minute)); }; then
    next_epoch=$(TZ="$TIMEZONE" date -d "today $hour:$minute" +%s)
  else
    next_epoch=$(TZ="$TIMEZONE" date -d "tomorrow $hour:$minute" +%s)
  fi

  TZ="$TIMEZONE" date -d "@$next_epoch" '+%Y-%m-%d %H:%M %Z'
}

send_notification() {
  local message="$1"
  # Example notifier calls — customize as needed:
  if jq -e '.notifiers.gotify.enabled' "$CONFIG_PATH" >/dev/null 2>&1; then
    local gotify_url gotify_token
    gotify_url=$(jq -r '.notifiers.gotify.url' "$CONFIG_PATH")
    gotify_token=$(jq -r '.notifiers.gotify.token' "$CONFIG_PATH")
    curl -s -X POST "$gotify_url/message?token=$gotify_token" -d "title=Addon Updater&message=$message" >/dev/null 2>&1
  fi

  if jq -e '.notifiers.mailrise.enabled' "$CONFIG_PATH" >/dev/null 2>&1; then
    local mailrise_url
    mailrise_url=$(jq -r '.notifiers.mailrise.url' "$CONFIG_PATH")
    curl -s -X POST "$mailrise_url" -d "$message" >/dev/null 2>&1
  fi

  if jq -e '.notifiers.apprise.enabled' "$CONFIG_PATH" >/dev/null 2>&1; then
    local apprise_url
    apprise_url=$(jq -r '.notifiers.apprise.url' "$CONFIG_PATH")
    curl -s -X POST "$apprise_url" -d "body=$message&title=Addon Updater" >/dev/null 2>&1
  fi
}

update_addon() {
  local addon_dir="$1"
  local addon_json="$addon_dir/config.json"
  local updater_json="$addon_dir/updater.json"
  local slug
  slug=$(jq -r '.slug' "$addon_json")

  local current_version new_version image
  current_version=$(jq -r '.version // ""' "$addon_json")

  # Try to get image from config.json or updater.json or build.json
  image=$(jq -r '.image // empty' "$addon_json" 2>/dev/null)
  if [[ -z "$image" && -f "$updater_json" ]]; then
    image=$(jq -r '.image // empty' "$updater_json" 2>/dev/null)
  fi
  # TODO: Add build.json if applicable

  if [[ -z "$image" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' missing image field, skipping."
    return
  fi

  # Determine registry and repo/image from image string (handle JSON or plain)
  # image can be JSON mapping arch->image or plain string
  if jq -e . >/dev/null 2>&1 <<<"$image"; then
    # JSON image mapping
    image=$(jq -r 'to_entries[0].value' <<<"$image")  # Pick first arch image for checking
  fi

  # Strip tag or get full image reference
  local image_name image_tag
  if [[ "$image" == *":"* ]]; then
    image_name="${image%:*}"
    image_tag="${image##*:}"
  else
    image_name="$image"
    image_tag="latest"
  fi

  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  # Fetch latest tag from Docker Hub or LinuxServer.io or GitHub

  # -- Docker Hub --
  # If image_name contains "/", assume docker hub official or user repo
  local latest_tag=""
  local last_updated=""
  if [[ "$image_name" == *"/"* ]]; then
    # DockerHub API: https://registry.hub.docker.com/v2/repositories/<repo>/tags?page_size=100
    local repo_api_url="https://registry.hub.docker.com/v2/repositories/$image_name/tags?page_size=100"

    local tags_json
    tags_json=$(curl -s "$repo_api_url" || echo "")

    if [[ -z "$tags_json" ]]; then
      log "$COLOR_YELLOW" "⚠️ No tags info retrieved from Docker Hub for $image_name"
      latest_tag="latest"
    else
      # Find latest tag by date
      latest_tag=$(jq -r '
        .results | sort_by(.last_updated) | last | .name
      ' <<<"$tags_json")

      last_updated=$(jq -r '
        .results | sort_by(.last_updated) | last | .last_updated
      ' <<<"$tags_json")
    fi
  fi

  # TODO: Add GitHub and LinuxServer.io tag fetching here if needed

  if [[ -z "$latest_tag" ]]; then
    latest_tag="latest"
  fi

  log "$COLOR_GREEN" "🚀 Latest version: $latest_tag"
  log "$COLOR_GREEN" "🕒 Last updated: $(date -d "$last_updated" +'%d-%m-%Y %H:%M' 2>/dev/null || echo 'unknown')"

  if [[ "$current_version" != "$latest_tag" ]]; then
    log "$COLOR_YELLOW" "⬆️  Updating $slug from $current_version to $latest_tag"

    # Update version in config.json
    jq --arg v "$latest_tag" '.version = $v' "$addon_json" > "$addon_json.tmp" && mv "$addon_json.tmp" "$addon_json"

    # Update updater.json if exists
    if [[ -f "$updater_json" ]]; then
      jq --arg v "$latest_tag" --arg dt "$(date +'%d-%m-%Y %H:%M')" --arg img "$image" --arg slug "$slug" \
         '.upstream_version = $v | .last_update = $dt | .image = $img | .slug = $slug' \
         "$updater_json" > "$updater_json.tmp" && mv "$updater_json.tmp" "$updater_json"
      log "$COLOR_GREEN" "✅ Updated updater.json for $slug"
    fi

    # Update changelog
    local changelog_file="$addon_dir/CHANGELOG.md"
    echo -e "v$latest_tag ($(date +'%d-%m-%Y'))\n\n    Update to latest version of $image_name:$latest_tag\n" | cat - "$changelog_file" > temp && mv temp "$changelog_file"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

    send_notification "Addon $slug updated from $current_version to $latest_tag"
  else
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
  fi

  log "$COLOR_RESET" "----------------------------"
}

main() {
  log "$COLOR_BLUE" "🔮 Add-on Updater started"
  log "$COLOR_BLUE" "📅 Cron schedule: $CRON_SCHEDULE (Timezone: $TIMEZONE)"
  log "$COLOR_BLUE" "🏃 Running initial update check..."

  cd "$REPO_DIR"
  git pull origin main || { log "$COLOR_RED" "❌ Git pull failed"; exit 1; }
  log "$COLOR_GREEN" "✅ Git pull successful."

  for addon_dir in addons/*; do
    [[ -d "$addon_dir" ]] || continue
    update_addon "$addon_dir"
  done

  # Next run time
  local next_run
  next_run=$(calc_next_run "$CRON_SCHEDULE")
  log "$COLOR_BLUE" "⏰ Next scheduled run: $next_run"

  # Commit changes if any
  if [[ -n $(git status --porcelain) ]]; then
    git add .
    git commit -m "Update addons metadata: $(date)"
    git push origin main
    log "$COLOR_GREEN" "✅ Changes committed and pushed."
  else
    log "$COLOR_YELLOW" "ℹ️ No changes to commit."
  fi
}

main
