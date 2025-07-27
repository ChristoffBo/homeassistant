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

log() {
  local color="$1"
  shift
  echo -e "$(date '+[%Y-%m-%d %H:%M:%S %Z]') ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Load configuration options
TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
CRON_SCHEDULE=$(jq -r '.cron // "0 3 * * *"' "$CONFIG_PATH")
GITHUB_REPO=$(jq -r '.repo // "https://github.com/ChristoffBo/homeassistant.git"' "$CONFIG_PATH")

NOTIFY_GOTIFY_URL=$(jq -r '.gotify.url // empty' "$CONFIG_PATH")
NOTIFY_MAILRISE_URL=$(jq -r '.mailrise.url // empty' "$CONFIG_PATH")
NOTIFY_APPRISE_URL=$(jq -r '.apprise.url // empty' "$CONFIG_PATH")

export TZ

notify() {
  local title="$1"
  local message="$2"

  if [[ -n "$NOTIFY_GOTIFY_URL" ]]; then
    curl -s -X POST "$NOTIFY_GOTIFY_URL/message" -F "title=$title" -F "message=$message" > /dev/null || true
  fi

  if [[ -n "$NOTIFY_MAILRISE_URL" ]]; then
    curl -s -X POST "$NOTIFY_MAILRISE_URL" -d "$message" > /dev/null || true
  fi

  if [[ -n "$NOTIFY_APPRISE_URL" ]]; then
    curl -s -X POST "$NOTIFY_APPRISE_URL" -d "$message" > /dev/null || true
  fi
}

git_pull_repo() {
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "$COLOR_BLUE" "Cloning repo $GITHUB_REPO into $REPO_DIR"
    git clone "$GITHUB_REPO" "$REPO_DIR"
  else
    log "$COLOR_BLUE" "Pulling latest changes from GitHub repo"
    git -C "$REPO_DIR" pull
  fi
}

git_commit_push() {
  local message="$1"
  git -C "$REPO_DIR" add .
  if git -C "$REPO_DIR" commit -m "$message"; then
    git -C "$REPO_DIR" push
    return 0
  else
    log "$COLOR_YELLOW" "No changes to commit."
    return 1
  fi
}

get_latest_dockerhub_tag() {
  local image="$1"
  local tags_json
  tags_json=$(curl -sfL "https://registry.hub.docker.com/v2/repositories/${image}/tags?page_size=100" || echo "{}")
  echo "$tags_json" | jq -r '.results[].name' | grep -vE 'latest|rc|beta' | head -n1 || echo "latest"
}

get_latest_github_tag() {
  local repo="$1"
  local tag
  tag=$(curl -sfL "https://api.github.com/repos/${repo}/releases/latest" | jq -r '.tag_name // empty')
  echo "${tag:-latest}"
}

get_latest_linuxserver_tag() {
  local image="$1"
  get_latest_dockerhub_tag "$image"
}

update_addon() {
  local addon_dir="$1"
  local slug
  slug=$(basename "$addon_dir")

  local config_file="$addon_dir/config.json"
  if [[ ! -f "$config_file" ]]; then
    log "$COLOR_YELLOW" "⚠️ Missing config.json for $slug, skipping"
    return
  fi

  local image version
  image=$(jq -r '.image // empty' "$config_file")
  version=$(jq -r '.version // empty' "$config_file")

  if jq -e '.image | type=="object"' "$config_file" >/dev/null 2>&1; then
    image=$(jq -r '.image.amd64 // empty' "$config_file")
  fi

  if [[ -z "$image" ]]; then
    log "$COLOR_YELLOW" "⚠️ No image field for $slug, skipping"
    return
  fi

  log "$COLOR_BLUE" "🧩 Addon: $slug"
  log "$COLOR_BLUE" "🔢 Current version: $version"
  log "$COLOR_BLUE" "📦 Image: $image"

  local latest_tag=""
  if [[ "$image" =~ github\.com ]]; then
    local github_repo
    github_repo=$(echo "$image" | sed -n 's#.*/\([^/:]*\/[^/:]*\).*#\1#p')
    if [[ -n "$github_repo" ]]; then
      latest_tag=$(get_latest_github_tag "$github_repo")
    fi
  elif [[ "$image" =~ lscr.io ]]; then
    latest_tag=$(get_latest_linuxserver_tag "$image")
  else
    local dockerhub_image="${image#*/}"
    if [[ "$dockerhub_image" == "$image" ]]; then
      dockerhub_image="$image"
    fi
    latest_tag=$(get_latest_dockerhub_tag "$dockerhub_image")
  fi

  if [[ -z "$latest_tag" ]]; then
    log "$COLOR_YELLOW" "⚠️ No latest tag found for $slug, skipping"
    return
  fi

  log "$COLOR_BLUE" "🚀 Latest version: $latest_tag"

  if [[ "$latest_tag" == "$version" ]]; then
    log "$COLOR_GREEN" "✔️ $slug is already up to date ($version)"
    return
  fi

  log "$COLOR_YELLOW" "⬆️ Updating $slug from $version to $latest_tag"

  jq --arg ver "$latest_tag" '.version = $ver' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

  local updater_file="$addon_dir/updater.json"
  if [[ -f "$updater_file" ]]; then
    local last_update
    last_update=$(date "+%d-%m-%Y %H:%M")
    local image_obj
    if jq -e '.image | type=="object"' "$config_file" >/dev/null 2>&1; then
      image_obj=$(jq '.image' "$config_file")
      jq --arg ver "$latest_tag" --arg dt "$last_update" --argjson img "$image_obj" --arg slug "$slug" \
        '.upstream_version = $ver | .last_update = $dt | .image = $img | .slug = $slug' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"
    else
      jq --arg ver "$latest_tag" --arg dt "$last_update" --arg img "$image" --arg slug "$slug" \
        '.upstream_version = $ver | .last_update = $dt | .image = $img | .slug = $slug' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"
    fi
    log "$COLOR_GREEN" "✅ Updated updater.json for $slug"
  fi

  local changelog_file="$addon_dir/CHANGELOG.md"
  local dt_changelog
  dt_changelog=$(date "+%d-%m-%Y %H:%M")
  {
    echo "v$latest_tag ($dt_changelog)"
    echo "  - Updated to latest Docker image tag $latest_tag"
    echo
    if [[ "$latest_tag" != "latest" ]]; then
      echo "  Changelog: https://hub.docker.com/r/${image}/tags"
    fi
  } >> "$changelog_file"
  log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

  UPDATED=1
}

main() {
  log "$COLOR_PURPLE" "🔮 Add-on Updater started"
  log "$COLOR_BLUE" "📅 Cron schedule: $CRON_SCHEDULE (Timezone: $TZ)"
  log "$COLOR_BLUE" "🏃 Running update check..."

  git_pull_repo

  UPDATED=0

  for addon_dir in "$REPO_DIR"/*/; do
    [[ -d "$addon_dir" ]] || continue
    update_addon "$addon_dir"
  done

  if (( UPDATED )); then
    log "$COLOR_GREEN" "🚀 Committing and pushing updates..."
    if git_commit_push "Updated addon versions and changelogs"; then
      notify "Add-on Updater" "Add-ons updated and pushed to GitHub successfully."
      log "$COLOR_GREEN" "✅ Git commit and push successful."
    else
      log "$COLOR_YELLOW" "⚠️ No changes to commit or push."
    fi
  else
    log "$COLOR_GREEN" "✔️ No updates found."
  fi

  log "$COLOR_PURPLE" "🔮 Add-on Updater finished."
}

main
