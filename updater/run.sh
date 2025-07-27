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

log() {
  local color="$1"
  shift
  local timestamp
  timestamp=$(date "+%Y-%m-%d %H:%M:%S %Z")
  echo -e "[${timestamp}] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

read_version() {
  local file="$1"
  if [[ -f "$file" ]]; then
    jq -r '.version // empty' "$file" 2>/dev/null | tr -d '\n\r'
  else
    echo ""
  fi
}

read_image() {
  local addon_dir="$1"
  local image=""
  for file in config.json build.json updater.json; do
    local filepath="$addon_dir/$file"
    if [[ -f "$filepath" ]]; then
      image=$(jq -r '.image // empty' "$filepath" 2>/dev/null)
      # If image is JSON object (multiarch), pick amd64 or first
      if echo "$image" | jq -e 'type=="object"' >/dev/null 2>&1; then
        image=$(echo "$image" | jq -r '.amd64 // .[keys[0]]')
      fi
      if [[ -n "$image" && "$image" != "null" ]]; then
        echo "$image"
        return 0
      fi
    fi
  done
  echo ""
}

fetch_docker_tags() {
  local repo="$1"
  curl -s "https://hub.docker.com/v2/repositories/${repo}/tags?page_size=100" || echo ""
}

get_latest_tag() {
  local repo="$1"
  local tags_json="$2"
  echo "$tags_json" | jq -r '.results[].name' 2>/dev/null | \
    grep -E '^[0-9]+\.[0-9]+(\.[0-9]+)?$' | sort -rV | head -n1
}

version_equal() {
  [[ "$1" == "$2" ]]
}

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

main() {
  local cron_schedule
  cron_schedule=$(jq -r '.cron_schedule // empty' "$CONFIG_PATH")

  local github_url github_user github_token
  github_url=$(jq -r '.github.url // empty' "$CONFIG_PATH" | sed 's/\.git$//')
  github_user=$(jq -r '.github.username // empty' "$CONFIG_PATH")
  github_token=$(jq -r '.github.token // empty' "$CONFIG_PATH")

  if [[ -z "$github_url" || -z "$github_user" || -z "$github_token" ]]; then
    log "$COLOR_YELLOW" "⚠️ GitHub credentials missing or incomplete; skipping git push."
    push_enabled=0
  else
    push_enabled=1
    git -C "$REPO_DIR" remote set-url origin "https://${github_user}:${github_token}@${github_url#https://}"
  fi

  local addons=()
  while IFS= read -r -d $'\0' dir; do
    local basename
    basename=$(basename "$dir")
    # Skip hidden folders (like .git)
    if [[ "$basename" == .* ]]; then
      continue
    fi
    addons+=("$basename")
  done < <(find "$REPO_DIR" -mindepth 1 -maxdepth 1 -type d -print0)

  local updated_any=0
  for addon in "${addons[@]}"; do
    log "$COLOR_PURPLE" "🧩 Addon: $addon"

    local version
    version=""
    for file in config.json build.json updater.json; do
      local v
      v=$(read_version "$REPO_DIR/$addon/$file")
      if [[ -n "$v" ]]; then
        version="$v"
        break
      fi
    done

    local image
    image=$(read_image "$REPO_DIR/$addon")

    if [[ -z "$image" ]]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$addon' has no Docker image defined, skipping."
      echo "----------------------------" | tee -a "$LOG_FILE"
      continue
    fi

    local repo tag
    if [[ "$image" == *":"* ]]; then
      repo="${image%%:*}"
      tag="${image##*:}"
    else
      repo="$image"
      tag="latest"
    fi

    if [[ "$version" == "latest" || "$tag" == "latest" ]]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$addon' uses 'latest' tag; will try to find latest specific version tag."

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

    for file in config.json build.json updater.json; do
      local filepath="$REPO_DIR/$addon/$file"
      if [[ -f "$filepath" ]]; then
        jq --arg v "$tag" '.version=$v' "$filepath" > "${filepath}.tmp" && mv "${filepath}.tmp" "$filepath"
        break
      fi
    done

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

  if [[ -n "$cron_schedule" ]]; then
    log "$COLOR_BLUE" "⏰ Starting cron scheduler with schedule: $cron_schedule"
    echo "$cron_schedule /run.sh" | crontab -
    cron -f
  else
    log "$COLOR_YELLOW" "⚠️ Cron not configured, exiting after this run."
  fi
}

main "$@"
