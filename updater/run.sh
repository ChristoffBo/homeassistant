#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Colors
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

# Read timezone from config, fallback
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
CRON_SCHEDULE=$(jq -r '.cron // "0 3 * * *"' "$CONFIG_PATH")

log() {
  local color="$1"
  shift
  echo -e "[$(TZ=$TIMEZONE date '+%Y-%m-%d %H:%M:%S %Z')] ${color}$*${COLOR_RESET}"
}

# Notifications only on update
send_notification() {
  local message="$1"
  local level="${2:-info}"

  # Gotify
  local gotify_url=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
  local gotify_token=$(jq -r '.gotify.token // empty' "$CONFIG_PATH")
  if [[ -n "$gotify_url" && -n "$gotify_token" ]]; then
    curl -s -X POST "$gotify_url/message?token=$gotify_token" -d "title=Addon Update&message=$message&priority=5" >/dev/null || true
  fi

  # Mailrise
  local mailrise_url=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
  if [[ -n "$mailrise_url" ]]; then
    curl -s -X POST "$mailrise_url" -d "$message" >/dev/null || true
  fi

  # Apprise
  local apprise_url=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")
  if [[ -n "$apprise_url" ]]; then
    curl -s -X POST -H "Content-Type: application/json" -d "{\"body\":\"$message\",\"title\":\"Addon Update\",\"priority\":5}" "$apprise_url" >/dev/null || true
  fi
}

# Function to fetch latest tag depending on registry
fetch_latest_docker_tag() {
  local image="$1"
  local registry repo namespace url tags latest_tag

  local image_no_tag="${image%%:*}"

  if [[ "$image_no_tag" == ghcr.io/* ]]; then
    registry="ghcr"
    repo="${image_no_tag#ghcr.io/}"
  elif [[ "$image_no_tag" == lscr.io/* ]]; then
    registry="linuxserver"
    repo="${image_no_tag#lscr.io/}"
  else
    registry="dockerhub"
    if [[ "$image_no_tag" == *"/"* ]]; then
      namespace="${image_no_tag%%/*}"
      repo="${image_no_tag#*/}"
    else
      namespace="library"
      repo="$image_no_tag"
    fi
  fi

  case "$registry" in
    dockerhub)
      url="https://registry.hub.docker.com/v2/repositories/$namespace/$repo/tags?page_size=100"
      tags=$(curl -s "$url" | jq -r '.results[].name' || echo "")
      ;;
    ghcr)
      local owner="${repo%%/*}"
      local package="${repo#*/}"
      url="https://api.github.com/orgs/$owner/packages/container/$package/versions"
      tags=$(curl -s "$url" | jq -r '.[].metadata.container.tags[]?' || echo "")
      ;;
    linuxserver)
      url="https://registry.hub.docker.com/v2/repositories/linuxserver/$repo/tags?page_size=100"
      tags=$(curl -s "$url" | jq -r '.results[].name' || echo "")
      ;;
  esac

  if [[ -z "$tags" ]]; then
    log "$COLOR_YELLOW" "⚠️ No tags found for $image, falling back to 'latest'"
    echo "latest"
    return
  fi

  latest_tag=$(echo "$tags" | grep -v '^latest$' | sort -V | tail -n1)
  [[ -z "$latest_tag" ]] && latest_tag="latest"
  echo "$latest_tag"
}

# Function to update JSON files safely
update_json_file() {
  local file="$1"
  local new_version="$2"
  local new_image="$3"
  local now_dt
  now_dt=$(TZ=$TIMEZONE date '+%d-%m-%Y %H:%M')

  if [[ ! -f "$file" ]]; then
    log "$COLOR_YELLOW" "⚠️ File $file not found, skipping."
    return 1
  fi

  # Determine slug from file content
  local slug
  slug=$(jq -r '.slug // empty' "$file")

  # Update fields
  jq --arg v "$new_version" --arg dt "$now_dt" --arg img "$new_image" --arg slug "$slug" \
    '.upstream_version = $v | .last_update = $dt | .image = $img | .slug = $slug' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
  
  log "$COLOR_GREEN" "✅ Updated $file"
}

# Update changelog
update_changelog() {
  local addon_dir="$1"
  local addon_name="$2"
  local new_version="$3"
  local changelog_url="$4"
  local now_date
  now_date=$(TZ=$TIMEZONE date '+%d-%m-%Y')

  local changelog_file="${addon_dir}/CHANGELOG.md"

  echo -e "v${new_version} (${now_date})\n\n    Update to latest version (${changelog_url})\n" >> "$changelog_file"
  log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $addon_name"
}

# Calculate next cron run time
calc_next_run() {
  local cron_expr="$1"
  local now_epoch=$(date +%s)
  local next_epoch

  # Use `cronnext` if installed (preferred)
  if command -v cronnext &>/dev/null; then
    next_epoch=$(cronnext "$cron_expr" | head -1)
  else
    # fallback: parse hours and minutes, calculate next run today or tomorrow
    local hour minute
    hour=$(echo "$cron_expr" | awk '{print $2}')
    minute=$(echo "$cron_expr" | awk '{print $1}')
    local now_hour now_minute
    now_hour=$(date +%H)
    now_minute=$(date +%M)
    if (( 10#$hour > 10#$now_hour || (10#$hour == 10#$now_hour && 10#$minute > 10#$now_minute) )); then
      next_epoch=$(date -d "today $hour:$minute" +%s)
    else
      next_epoch=$(date -d "tomorrow $hour:$minute" +%s)
    fi
  fi
  date -d "@$next_epoch" '+%Y-%m-%d %H:%M:%S %Z'
}

main() {
  log "$COLOR_PURPLE" "🔮 Add-on Updater started"
  log "$COLOR_BLUE" "📅 Cron schedule: $CRON_SCHEDULE (Timezone: $TIMEZONE)"
  local next_run
  next_run=$(calc_next_run "$CRON_SCHEDULE")
  log "$COLOR_BLUE" "⏳ Next run scheduled at: $next_run"
  log "$COLOR_BLUE" "🏃 Running initial update check..."

  cd "$REPO_DIR"
  git pull origin main || { log "$COLOR_RED" "❌ Git pull failed"; exit 1; }
  log "$COLOR_GREEN" "✅ Git pull successful."
  log "$COLOR_BLUE" "----------------------------"

  local updated_any=false

  # Iterate each addon directory
  for addon_dir in addons/*; do
    [[ ! -d "$addon_dir" ]] && continue

    local config_file="${addon_dir}/config.json"
    local updater_file="${addon_dir}/updater.json"
    local build_file="${addon_dir}/build.json"

    # Parse addon data, skip if no config.json
    if [[ ! -f "$config_file" ]]; then
      log "$COLOR_YELLOW" "⚠️ $addon_dir missing config.json, skipping."
      continue
    fi

    local addon_name slug image current_version
    addon_name=$(jq -r '.name' "$config_file")
    slug=$(jq -r '.slug' "$config_file")
    image=$(jq -r '.image // .docker_image // empty' "$config_file")

    # If image is empty, try updater.json for image object (multi-arch)
    if [[ -z "$image" && -f "$updater_file" ]]; then
      # Compose image string from JSON object (e.g. aarch64, amd64)
      image=$(jq -r 'if type=="object" then (.aarch64 // .amd64 // empty) else empty end' "$updater_file")
    fi

    if [[ -z "$image" ]]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$slug' missing image field, skipping."
      continue
    fi

    # Current version fallback: check config.json version field or updater.json upstream_version
    current_version=$(jq -r '.version // empty' "$config_file")
    if [[ -z "$current_version" && -f "$updater_file" ]]; then
      current_version=$(jq -r '.upstream_version // empty' "$updater_file")
    fi
    if [[ -z "$current_version" ]]; then
      current_version="unknown"
    fi

    log "$COLOR_PURPLE" "🧩 Addon: $slug"
    log "$COLOR_BLUE" "🔢 Current version: $current_version"
    log "$COLOR_BLUE" "📦 Image: $image"

    # Fetch latest tag from Docker registries
    local latest_tag
    latest_tag=$(fetch_latest_docker_tag "$image")

    log "$COLOR_GREEN" "🚀 Latest version: $latest_tag"

    # Simple last update date from updater.json or fallback
    local last_update
    if [[ -f "$updater_file" ]]; then
      last_update=$(jq -r '.last_update // empty' "$updater_file")
    else
      last_update=""
    fi
    [[ -z "$last_update" ]] && last_update="unknown"

    log "$COLOR_BLUE" "🕒 Last updated: $last_update"

    if [[ "$latest_tag" != "$current_version" ]]; then
      log "$COLOR_YELLOW" "⬆️  Updating $slug from $current_version to $latest_tag"

      # Update config.json version field
      jq --arg v "$latest_tag" '.version = $v' "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"

      # Update updater.json if exists
      if [[ -f "$updater_file" ]]; then
        update_json_file "$updater_file" "$latest_tag" "$image"
      fi

      # Update build.json if exists
      if [[ -f "$build_file" ]]; then
        update_json_file "$build_file" "$latest_tag" "$image"
      fi

      # Update changelog
      local changelog_url=""
      if [[ "$image" == lscr.io/linuxserver/* ]]; then
        # Guess LinuxServer changelog URL
        local app_name="${slug,,}"
        changelog_url="https://github.com/linuxserver/docker-$app_name/releases"
      elif [[ "$image" == ghcr.io/* ]]; then
        local owner_repo="${image#ghcr.io/}"
        owner_repo="${owner_repo%%:*}"
        changelog_url="https://github.com/$owner_repo/releases"
      else
        changelog_url=""
      fi
      update_changelog "$addon_dir" "$slug" "$latest_tag" "$changelog_url"

      send_notification "Addon *$slug* updated from $current_version to $latest_tag"
      updated_any=true
    else
      log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
    fi

    log "$COLOR_BLUE" "----------------------------"
  done

  if $updated_any; then
    git add .
    git commit -m "Update addons to latest upstream versions ($(TZ=$TIMEZONE date '+%Y-%m-%d %H:%M:%S %Z'))" || true
    git push origin main || log "$COLOR_RED" "❌ Git push failed"
  else
    log "$COLOR_BLUE" "No changes to commit."
  fi
}

main
