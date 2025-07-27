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

# Log function with timestamp & color
log() {
  local color="$1"
  shift
  local timestamp
  timestamp=$(date "+%Y-%m-%d %H:%M:%S %Z")
  echo -e "[${timestamp}] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Read version from JSON file safely
read_version() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local version
    version=$(jq -r '.version // empty' "$file" 2>/dev/null | tr -d '\n\r')
    echo "$version"
  else
    echo ""
  fi
}

# Get Docker Hub tags for a repository (first page, max 100 tags)
fetch_docker_tags() {
  local repo="$1"
  curl -s "https://hub.docker.com/v2/repositories/${repo}/tags?page_size=100" || echo ""
}

# Extract the best semver tag, ignoring "latest" or any non-version tags
get_latest_tag() {
  local repo="$1"
  local tags_json="$2"
  # Extract tag names excluding 'latest' and non-semver tags, sort descending semver, pick first
  echo "$tags_json" | jq -r '.results[].name' 2>/dev/null | \
    grep -E '^[0-9]+\.[0-9]+(\.[0-9]+)?$' | sort -rV | head -n1
}

# Compare semantic versions: returns 0 if $1 == $2, 1 if different
version_equal() {
  [[ "$1" == "$2" ]]
}

# Update CHANGELOG.md or create it
update_changelog() {
  local addon="$1"
  local old_ver="$2"
  local new_ver="$3"
  local changelog_file="${REPO_DIR}/${addon}/CHANGELOG.md"
  local date_stamp
  date_stamp=$(date "+%Y-%m-%d %H:%M")
  
  if [[ ! -f "$changelog_file" ]]; then
    echo "# Changelog for $addon" > "$changelog_file"
  fi
  echo -e "\n## Updated to $new_ver on $date_stamp" >> "$changelog_file"
  log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $addon"
}

# Send notification if configured
send_notification() {
  local message="$1"
  local type url token
  type=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
  url=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
  token=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")
  
  if [[ -z "$type" || -z "$url" ]]; then
    log "$COLOR_YELLOW" "⚠️ Notifier type or URL not configured; skipping notifications."
    return
  fi
  
  case "$type" in
    gotify)
      curl -s -X POST "${url%/}/message" \
        -H "X-Gotify-Key: $token" \
        -F "title=Addon Updater" \
        -F "message=$message" \
        -F "priority=5" >/dev/null 2>&1 || log "$COLOR_RED" "❌ Gotify notification failed."
      ;;
    mailrise)
      curl -s -X POST "$url" -H "Content-Type: text/plain" --data "$message" >/dev/null 2>&1 || log "$COLOR_RED" "❌ Mailrise notification failed."
      ;;
    apprise)
      curl -s "$url" -d "$message" >/dev/null 2>&1 || log "$COLOR_RED" "❌ Apprise notification failed."
      ;;
    *)
      log "$COLOR_RED" "❌ Unknown notifier type: $type"
      ;;
  esac
}

# Get architecture suffix for Docker tags (e.g., amd64-)
strip_arch_prefix() {
  local tag="$1"
  echo "$tag" | sed -E 's/^(amd64|armv7|aarch64|armhf|arm64)-//'
}

# Main updater loop
main() {
  # Read cron schedule
  local cron_schedule
  cron_schedule=$(jq -r '.cron_schedule // empty' "$CONFIG_PATH")
  
  # Read GitHub info for commit & push
  local github_url github_user github_token
  github_url=$(jq -r '.github.url // empty' "$CONFIG_PATH" | sed 's/\.git$//')
  github_user=$(jq -r '.github.username // empty' "$CONFIG_PATH")
  github_token=$(jq -r '.github.token // empty' "$CONFIG_PATH")

  if [[ -z "$github_url" || -z "$github_user" || -z "$github_token" ]]; then
    log "$COLOR_YELLOW" "⚠️ GitHub credentials missing or incomplete; skipping git push."
    push_enabled=0
  else
    push_enabled=1
    # Setup git remote with token
    git -C "$REPO_DIR" remote set-url origin "https://${github_user}:${github_token}@${github_url#https://}"
  fi

  # Load list of addons (folders in REPO_DIR)
  local addons=()
  while IFS= read -r -d $'\0' addon_dir; do
    addons+=("$(basename "$addon_dir")")
  done < <(find "$REPO_DIR" -mindepth 1 -maxdepth 1 -type d -print0)

  local updated_any=0
  for addon in "${addons[@]}"; do
    log "$COLOR_PURPLE" "🧩 Addon: $addon"

    # Find version: config.json -> build.json -> updater.json
    local version=""
    for file in config.json build.json updater.json; do
      version=$(read_version "$REPO_DIR/$addon/$file")
      if [[ -n "$version" ]]; then
        break
      fi
    done

    # Read docker image from config.json (for simplicity)
    local image
    image=$(jq -r '.image // empty' "$REPO_DIR/$addon/config.json" 2>/dev/null || echo "")
    
    # If image is an object (multiarch), pick architecture or default amd64
    if echo "$image" | jq -e 'type=="object"' >/dev/null 2>&1; then
      # Prefer amd64
      image=$(echo "$image" | jq -r '.amd64 // empty')
      if [[ -z "$image" ]]; then
        # fallback to any available
        image=$(echo "$image" | jq -r '.[keys[0]]')
      fi
    fi
    
    if [[ -z "$image" || "$image" == "null" ]]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$addon' has no Docker image defined, skipping."
      echo "----------------------------" | tee -a "$LOG_FILE"
      continue
    fi

    # Split image into repo and tag
    local repo tag
    if [[ "$image" == *":"* ]]; then
      repo="${image%%:*}"
      tag="${image##*:}"
    else
      repo="$image"
      tag="latest"
    fi

    # Skip if current version is 'latest'
    if [[ "$version" == "latest" || "$tag" == "latest" ]]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$addon' uses 'latest' tag; will try to find latest specific version tag."
      
      # Fetch tags from Docker Hub
      local tags_json
      tags_json=$(fetch_docker_tags "$repo")
      if [[ -z "$tags_json" ]]; then
        log "$COLOR_RED" "❌ Could not fetch tags for $repo"
        echo "----------------------------" | tee -a "$LOG_FILE"
        continue
      fi
      
      local latest_tag
      latest_tag=$(get_latest_tag "$repo" "$tags_json")
      if [[ -z "$latest_tag" ]]; then
        log "$COLOR_RED" "❌ No valid version tag found for $repo"
        echo "----------------------------" | tee -a "$LOG_FILE"
        continue
      fi

      tag="$latest_tag"
    fi

    log "$COLOR_BLUE" "🔢 Current version: $version"
    log "$COLOR_BLUE" "📦 Image: $repo:$tag"

    if version_equal "$version" "$tag"; then
      log "$COLOR_GREEN" "✔️ $addon is already up to date ($version)"
      echo "----------------------------" | tee -a "$LOG_FILE"
      continue
    fi

    log "$COLOR_YELLOW" "⬆️  Updating $addon from $version to $tag"

    # Update version in config.json or build.json or updater.json (in that order)
    for file in config.json build.json updater.json; do
      local filepath="$REPO_DIR/$addon/$file"
      if [[ -f "$filepath" ]]; then
        jq --arg v "$tag" '.version=$v' "$filepath" > "${filepath}.tmp" && mv "${filepath}.tmp" "$filepath"
        break
      fi
    done

    # Update changelog
    update_changelog "$addon" "$version" "$tag"

    updated_any=1
  done

  if [[ $updated_any -eq 1 ]]; then
    if [[ $push_enabled -eq 1 ]]; then
      log "$COLOR_BLUE" "🔄 Committing and pushing changes to GitHub..."
      git -C "$REPO_DIR" add .
      git -C "$REPO_DIR" commit -m "Update addon versions via updater script" || log "$COLOR_YELLOW" "⚠️ No changes to commit."
      git -C "$REPO_DIR" push origin main || log "$COLOR_RED" "❌ Git push failed."
    else
      log "$COLOR_YELLOW" "⚠️ Git push disabled due to missing credentials."
    fi

    send_notification "Addon versions updated."
  else
    log "$COLOR_BLUE" "ℹ️ No updates detected, no git commit or notification sent."
  fi

  # Run cron scheduler if set
  if [[ -n "$cron_schedule" ]]; then
    log "$COLOR_BLUE" "⏰ Starting cron scheduler with schedule: $cron_schedule"
    echo "$cron_schedule /run.sh" | crontab -
    cron -f
  else
    log "$COLOR_YELLOW" "⚠️ Cron not configured, exiting after this run."
  fi
}

main "$@"
