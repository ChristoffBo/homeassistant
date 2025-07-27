#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
export TZ

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_BLUE="\033[0;34m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  echo -e "[$(date '+%Y-%m-%d %H:%M:%S %Z')] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

notify_update() {
  local addon="$1"
  local old_version="$2"
  local new_version="$3"
  local message="Add-on '$addon' updated from $old_version to $new_version"

  local gotify_url=$(jq -r '.gotify_url // empty' "$CONFIG_PATH")
  local mailrise_url=$(jq -r '.mailrise_url // empty' "$CONFIG_PATH")
  local apprise_url=$(jq -r '.apprise_url // empty' "$CONFIG_PATH")

  if [[ -n "$gotify_url" ]]; then
    curl -s -X POST "$gotify_url" -F "title=Add-on Updated" -F "message=$message"
  elif [[ -n "$mailrise_url" ]]; then
    curl -s -X POST "$mailrise_url" -d "$message"
  elif [[ -n "$apprise_url" ]]; then
    curl -s "$apprise_url" -d "message=$message"
  else
    log "$COLOR_YELLOW" "⚠️ Notification method not configured or missing credentials."
  fi
}

get_latest_tag() {
  local image="$1"

  local repo=${image%%:*}
  local tag_list

  # Try Docker Hub first
  tag_list=$(curl -s "https://registry.hub.docker.com/v2/repositories/${repo}/tags?page_size=100" | jq -r '.results[].name' 2>/dev/null)
  if [[ -z "$tag_list" ]]; then
    # Try LinuxServer
    if [[ "$repo" == lscr.io/* ]]; then
      repo_name=$(basename "$repo")
      tag_list=$(curl -s "https://hub.docker.com/v2/repositories/linuxserver/$repo_name/tags?page_size=100" | jq -r '.results[].name' 2>/dev/null)
    fi
  fi

  # Try GitHub container registry
  if [[ -z "$tag_list" ]]; then
    org=$(echo "$repo" | cut -d'/' -f1)
    name=$(echo "$repo" | cut -d'/' -f2)
    tag_list=$(curl -s "https://ghcr.io/v2/$org/$name/tags/list" | jq -r '.tags[]' 2>/dev/null)
  fi

  echo "$tag_list" | grep -E '^[0-9]+(\.[0-9]+)*$' | sort -V | tail -n1
}

update_addon() {
  local addon_dir="$1"
  local addon_slug=$(basename "$addon_dir")

  log "$COLOR_BLUE" "🤩 Addon: $addon_slug"

  local config="$addon_dir/config.json"
  local build="$addon_dir/build.json"
  local updater="$addon_dir/updater.json"

  [[ ! -f "$config" ]] && log "$COLOR_RED" "⚠️ Missing config.json for $addon_slug" && return

  local current_version=$(jq -r '.version' "$config")
  local image=$(jq -r '.image // empty' "$config")

  [[ -z "$image" ]] && log "$COLOR_YELLOW" "⚠️ Add-on '$addon_slug' has no Docker image defined, skipping." && return

  log "$COLOR_YELLOW" "🔢 Current version: $current_version"
  log "$COLOR_PURPLE" "📦 Image: $image"

  local latest_tag=$(get_latest_tag "$image")

  if [[ -z "$latest_tag" ]]; then
    log "$COLOR_RED" "⚠️ Could not determine latest tag for $addon_slug, skipping update."
    return
  fi

  log "$COLOR_GREEN" "🚀 Latest version: $latest_tag"

  if [[ "$latest_tag" == "$current_version" ]]; then
    log "$COLOR_GREEN" "✔️ $addon_slug is already up to date ($latest_tag)"
  else
    log "$COLOR_BLUE" "⬆️  Updating $addon_slug from $current_version to $latest_tag"
    jq --arg v "$latest_tag" '.version = $v' "$config" > "$config.tmp" && mv "$config.tmp" "$config"

    if [[ -f "$build" ]]; then
      jq --arg v "$latest_tag" '.version = $v' "$build" > "$build.tmp" && mv "$build.tmp" "$build"
    fi
    if [[ -f "$updater" ]]; then
      jq --arg d "$(date '+%d-%m-%Y')" '.last_update = $d' "$updater" > "$updater.tmp" && mv "$updater.tmp" "$updater"
    else
      echo "{\n  \"last_update\": \"$(date '+%d-%m-%Y')\"\n}" > "$updater"
    fi

    local changelog="$addon_dir/CHANGELOG.md"
    echo -e "v$latest_tag ($(date '+%d-%m-%Y'))\n\n    Update to latest version from $image (tag: $latest_tag)\n" >> "$changelog"
    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $addon_slug"

    notify_update "$addon_slug" "$current_version" "$latest_tag"
  fi
  log "$COLOR_BLUE" "----------------------------"
}

main() {
  : > "$LOG_FILE"

  cd "$REPO_DIR"
  log "$COLOR_GREEN" "✅ Git pull successful."
  git pull --quiet || log "$COLOR_RED" "⚠️ Git pull failed."

  for addon in "$REPO_DIR"/*/; do
    [[ -d "$addon" ]] && update_addon "$addon"
  done

  if git diff --quiet; then
    log "$COLOR_YELLOW" "ℹ️ No changes to push."
  else
    git config --global user.email "updater@local"
    git config --global user.name "Updater Bot"
    git add .
    git commit -m "🚀 Update add-ons at $(date '+%Y-%m-%d %H:%M:%S')"
    if git push; then
      log "$COLOR_GREEN" "✅ Git push successful."
    else
      log "$COLOR_RED" "⚠️ Git push failed."
    fi
  fi
}

main
