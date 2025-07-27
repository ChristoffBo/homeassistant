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

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

load_addons() {
  jq -c '.addons[]' "$REPO_DIR/addons.json"
}

update_updater_json() {
  local addon_slug="$1"
  local new_version="$2"
  local new_image="$3"
  local timestamp="$4"

  local updater_file="$REPO_DIR/$addon_slug/updater.json"
  if [[ ! -f "$updater_file" ]]; then
    log "$COLOR_YELLOW" "🆕 Creating updater.json for $addon_slug"
    echo "{\"slug\":\"$addon_slug\",\"upstream_version\":\"$new_version\",\"image\":\"$new_image\",\"last_update\":\"$timestamp\"}" > "$updater_file"
  else
    jq --arg v "$new_version" --arg img "$new_image" --arg dt "$timestamp" \
      '.upstream_version = $v | .image = $img | .last_update = $dt' "$updater_file" > "${updater_file}.tmp" && mv "${updater_file}.tmp" "$updater_file"
    log "$COLOR_GREEN" "✅ Updated updater.json for $addon_slug"
  fi
}

update_changelog() {
  local addon_slug="$1"
  local new_version="$2"
  local changelog_url="$3"
  local timestamp="$4"

  local changelog_file="$REPO_DIR/$addon_slug/CHANGELOG.md"
  local header="v${new_version} (${timestamp})"

  if [[ ! -f "$changelog_file" ]]; then
    log "$COLOR_YELLOW" "🆕 Creating CHANGELOG.md for $addon_slug"
    {
      echo "# Changelog"
      echo ""
      echo "## $header"
      echo ""
      echo "- Updated to version $new_version"
      echo ""
      echo "Changelog URL: $changelog_url"
      echo ""
    } > "$changelog_file"
    return 0
  else
    if ! grep -qF "$header" "$changelog_file"; then
      {
        echo "## $header"
        echo ""
        echo "- Updated to version $new_version"
        echo ""
        echo "Changelog URL: $changelog_url"
        echo ""
        cat "$changelog_file"
      } > "${changelog_file}.tmp" && mv "${changelog_file}.tmp" "$changelog_file"
      log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $addon_slug"
      return 0
    fi
  fi
  return 1
}

check_latest_tag() {
  local image="$1"
  local repo tag

  repo="${image%%:*}"
  tag="${image#*:}"
  [[ "$repo" == "$tag" ]] && tag="latest"

  if [[ "$repo" =~ ^ghcr\.io/ ]] || [[ "$repo" =~ ^docker\.pkg\.github\.com/ ]]; then
    fetch_github_latest_tag "$repo"
    return
  fi

  if [[ "$repo" =~ ^lscr\.io/linuxserver/ ]]; then
    local dockerhub_repo=${repo#lscr.io/}
    fetch_dockerhub_latest_tag "$dockerhub_repo"
    return
  fi

  fetch_dockerhub_latest_tag "$repo"
}

fetch_github_latest_tag() {
  local repo="$1"
  local repo_path

  if [[ "$repo" =~ ^ghcr\.io/([^/]+/[^/]+) ]]; then
    repo_path="${BASH_REMATCH[1]}"
  elif [[ "$repo" =~ ^docker\.pkg\.github\.com/([^/]+/[^/]+/[^/]+) ]]; then
    repo_path="${BASH_REMATCH[1]}"
    repo_path=$(echo "$repo_path" | cut -d'/' -f1-2)
  else
    echo "latest"
    return
  fi

  local tags_json
  tags_json=$(curl -sSL "https://api.github.com/repos/$repo_path/packages/container/docker/versions?per_page=100")

  if [[ -z "$tags_json" ]]; then
    echo "latest"
    return
  fi

  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '[.[] | {tag: .metadata.container.tags[0], published_at: .created_at}] | sort_by(.published_at) | last | .tag')

  if [[ -z "$latest_tag" || "$latest_tag" == "null" ]]; then
    echo "latest"
  else
    echo "$latest_tag"
  fi
}

fetch_dockerhub_latest_tag() {
  local repo="$1"
  local tags_json

  tags_json=$(curl -sSL "https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100")

  if [[ -z "$tags_json" ]]; then
    echo "latest"
    return
  fi

  local latest_tag
  latest_tag=$(echo "$tags_json" | jq -r '[.results[] | select(.name != "latest")] | sort_by(.last_updated) | last | .name')

  if [[ -z "$latest_tag" || "$latest_tag" == "null" ]]; then
    echo "latest"
  else
    echo "$latest_tag"
  fi
}

send_notification() {
  local message="$1"

  local gotify_url mailrise_url apprise_url
  gotify_url=$(jq -r '.gotify_url // empty' "$CONFIG_PATH")
  mailrise_url=$(jq -r '.mailrise_url // empty' "$CONFIG_PATH")
  apprise_url=$(jq -r '.apprise_url // empty' "$CONFIG_PATH")

  if [[ -n "$gotify_url" ]]; then
    curl -s -X POST -H "Content-Type: application/json" \
      -d "{\"title\":\"Addon Updater\",\"message\":\"$message\",\"priority\":5}" \
      "$gotify_url" >/dev/null 2>&1
  fi

  if [[ -n "$mailrise_url" ]]; then
    curl -s -X POST -H "Content-Type: application/json" \
      -d "{\"subject\":\"Addon Updater\",\"message\":\"$message\"}" \
      "$mailrise_url" >/dev/null 2>&1
  fi

  if [[ -n "$apprise_url" ]]; then
    curl -s -X POST -d "message=$message" "$apprise_url" >/dev/null 2>&1
  fi
}

main() {
  log "$COLOR_BLUE" "🔮 Add-on Updater started"

  cd "$REPO_DIR"
  if git pull origin main; then
    log "$COLOR_GREEN" "✅ Git pull successful."
  else
    log "$COLOR_RED" "❌ Git pull failed. Exiting."
    exit 1
  fi

  local timestamp updated_any=false updates_summary=""

  timestamp=$(date '+%d-%m-%Y %H:%M')

  for addon_json in $(load_addons); do
    local slug image current_version latest_version

    slug=$(echo "$addon_json" | jq -r '.slug')
    local addon_path="$REPO_DIR/$slug"
    local config_file="$addon_path/config.json"

    if [[ ! -f "$config_file" ]]; then
      log "$COLOR_YELLOW" "⚠️ Config missing for $slug, skipping"
      continue
    fi

    current_version=$(jq -r '.version // empty' "$config_file")
    image=$(jq -r '.image // empty' "$config_file")

    if [[ -z "$image" ]]; then
      log "$COLOR_YELLOW" "⚠️ Image missing in config.json for $slug, skipping"
      continue
    fi

    log "$COLOR_BLUE" "🧩 Addon: $slug"
    log "$COLOR_YELLOW" "🔢 Current version: ${current_version:-none}"
    log "$COLOR_YELLOW" "📦 Image: $image"

    latest_version=$(check_latest_tag "$image")
    log "$COLOR_GREEN" "🚀 Latest version: $latest_version"
    log "$COLOR_BLUE" "🕒 Checked at: $timestamp"

    if [[ "$latest_version" == "$current_version" ]]; then
      log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
    else
      log "$COLOR_YELLOW" "⬆️  Updating $slug from ${current_version:-none} to $latest_version"

      # Update config.json version
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"

      # Update updater.json and changelog
      update_updater_json "$slug" "$latest_version" "$image" "$timestamp"
      update_changelog "$slug" "$latest_version" "https://github.com/ChristoffBo/homeassistant/releases" "$timestamp"

      git add "$config_file" "$addon_path/updater.json" "$addon_path/CHANGELOG.md" 2>/dev/null || true

      updated_any=true
      updates_summary+="$slug updated from ${current_version:-none} to $latest_version\n"
    fi

    echo "----------------------------"
  done

  if $updated_any; then
    if git commit -m "Update addons to latest versions"; then
      log "$COLOR_GREEN" "✅ Committed updates."
      if git push origin main; then
        log "$COLOR_GREEN" "✅ Pushed changes to GitHub."
        send_notification "Addon Updater completed. Updates:\n$updates_summary"
      else
        log "$COLOR_RED" "❌ Failed to push changes to GitHub."
      fi
    else
      log "$COLOR_YELLOW" "ℹ️ Nothing to commit."
    fi
  else
    log "$COLOR_BLUE" "ℹ️ No changes to commit."
  fi
}

main
