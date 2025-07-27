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
COLOR_PURPLE="\033[0;35m"

# Read timezone from config or fallback
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

log() {
  local color="$1"
  shift
  echo -e "[$(TZ=$TIMEZONE date +'%Y-%m-%d %H:%M:%S %Z')] ${color}$*${COLOR_RESET}"
  echo "[$(TZ=$TIMEZONE date +'%Y-%m-%d %H:%M:%S %Z')] $*" >> "$LOG_FILE"
}

# Fetch latest tag from Docker Hub - returns only clean tag or empty string
get_latest_docker_tag_dockerhub() {
  local image="$1"
  local repo="${image%%:*}"
  local namespace="library"
  local repo_name="$repo"

  if [[ "$repo" == *"/"* ]]; then
    namespace="${repo%%/*}"
    repo_name="${repo#*/}"
  fi

  local tags_json
  tags_json=$(curl -s "https://registry.hub.docker.com/v2/repositories/$namespace/$repo_name/tags/?page_size=100") || {
    echo ""
    return
  }

  local tags
  tags=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null || echo "")

  if [[ -z "$tags" ]]; then
    echo ""
    return
  fi

  # Filter tags that look like versions (e.g., v1.2.3, 1.2.3)
  local valid_tags
  valid_tags=$(echo "$tags" | grep -E '^[v]?[0-9]+([.-][0-9a-z]+)*$' | sort -V)

  if [[ -z "$valid_tags" ]]; then
    echo ""
    return
  fi

  echo "$valid_tags" | tail -n1
}

# Addon update function
update_addon() {
  local slug="$1"
  local addon_dir="$REPO_DIR/$slug"
  local config_json="$addon_dir/config.json"
  local build_json="$addon_dir/build.json"
  local version_file="$addon_dir/version"
  local changelog_file="$addon_dir/CHANGELOG.md"

  if [[ ! -f "$config_json" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' has no config.json, skipping."
    return
  fi

  # Read current version from config.json or version file
  local current_version
  current_version=$(jq -r '.version // empty' "$config_json" || true)
  if [[ -z "$current_version" ]] && [[ -f "$version_file" ]]; then
    current_version=$(cat "$version_file")
  fi
  current_version=${current_version:-"unknown"}

  # Read image from config.json (support both "image" or "docker_image" keys)
  local image
  image=$(jq -r '.image // .docker_image // empty' "$config_json" || true)
  if [[ -z "$image" ]]; then
    log "$COLOR_YELLOW" "⚠️ Add-on '$slug' has no Docker image defined, skipping."
    return
  fi

  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "📦 Image: $image"

  # Get latest version tag from Docker Hub
  local latest_version
  latest_version=$(get_latest_docker_tag_dockerhub "$image")

  if [[ -z "$latest_version" ]]; then
    log "$COLOR_YELLOW" "⚠️ Could not determine latest tag for $slug, skipping update."
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  if [[ "$latest_version" == "$current_version" ]]; then
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
    log "$COLOR_BLUE" "----------------------------"
    return
  fi

  # Update version in config.json and build.json if exists
  jq --arg ver "$latest_version" '.version = $ver' "$config_json" > "$config_json.tmp" && mv "$config_json.tmp" "$config_json"

  if [[ -f "$build_json" ]]; then
    # Fix invalid "version" fields if any, update version cleanly
    jq --arg ver "$latest_version" '.version = $ver' "$build_json" > "$build_json.tmp" && mv "$build_json.tmp" "$build_json"
  fi

  # Optionally save version file for fallback
  echo "$latest_version" > "$version_file"

  # Append changelog entry
  local now
  now=$(TZ=$TIMEZONE date +'%d-%m-%Y %H:%M')
  echo -e "v$latest_version ($now)\n\n    Updated to latest Docker Hub tag for image $image\n" >> "$changelog_file"

  log "$COLOR_YELLOW" "⬆️  Updating $slug from $current_version to $latest_version"
  log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

  # Commit changes (you can customize commit message)
  git -C "$REPO_DIR" add "$slug/config.json" "$slug/build.json" "$slug/CHANGELOG.md" "$slug/version" || true
  git -C "$REPO_DIR" commit -m "Update $slug to version $latest_version" || true

  # Notify if configured
  send_notification "$slug" "$current_version" "$latest_version"

  log "$COLOR_BLUE" "----------------------------"
}

send_notification() {
  local slug="$1"
  local old_version="$2"
  local new_version="$3"

  # Read notifier config from options.json
  local notify_url
  notify_url=$(jq -r '.notifier.url // empty' "$CONFIG_PATH" || echo "")

  if [[ -z "$notify_url" ]]; then
    log "$COLOR_YELLOW" "⚠️ Notification method not configured or missing credentials."
    return
  fi

  # Send simple notification via Gotify or webhook
  curl -s -X POST -H "Content-Type: application/json" -d "{\"title\":\"Addon Updated: $slug\",\"message\":\"Updated from $old_version to $new_version\"}" "$notify_url" >/dev/null 2>&1
  log "$COLOR_PURPLE" "🔔 Notification sent via configured notifier for $slug"
}

main() {
  log "$COLOR_PURPLE" "🔮 Checking your Github Repo for Updates..."

  # Pull latest from GitHub first
  if git -C "$REPO_DIR" pull --rebase; then
    log "$COLOR_GREEN" "✅ Git pull successful."
  else
    log "$COLOR_RED" "❌ Git pull failed, exiting."
    exit 1
  fi

  # Loop through each addon directory (exclude .git and non-directories)
  for addon in "$REPO_DIR"/*/; do
    slug=$(basename "$addon")
    # Skip .git or irrelevant folders
    [[ "$slug" == ".git" ]] && continue
    [[ ! -f "$addon/config.json" ]] && continue

    update_addon "$slug"
  done

  # Push changes back to GitHub with confirmation
  if git -C "$REPO_DIR" status --porcelain | grep . >/dev/null; then
    log "$COLOR_PURPLE" "⚠️ Changes detected, preparing to push to GitHub."
    git -C "$REPO_DIR" push origin main && log "$COLOR_GREEN" "✅ Changes pushed to GitHub."
  else
    log "$COLOR_GREEN" "ℹ️ No changes to push."
  fi
}

main
