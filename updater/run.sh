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
  echo -e "[$(date --utc +'%Y-%m-%d %H:%M:%S UTC')] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

# Load config options
CRON_SCHEDULE=$(jq -r '.cron_schedule // "0 3 * * *"' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "Africa/Johannesburg"' "$CONFIG_PATH")
NOTIFY_GOTIFY=$(jq -r '.notifiers.gotify.enabled // false' "$CONFIG_PATH")
NOTIFY_MAILRISE=$(jq -r '.notifiers.mailrise.enabled // false' "$CONFIG_PATH")
NOTIFY_APPRISE=$(jq -r '.notifiers.apprise.enabled // false' "$CONFIG_PATH")

# GitHub repo details for push/pull
GITHUB_USER=$(jq -r '.github.user // empty' "$CONFIG_PATH")
GITHUB_EMAIL=$(jq -r '.github.email // empty' "$CONFIG_PATH")
GITHUB_REPO="$REPO_DIR"
GIT_COMMIT_MSG="Addon versions updated by updater script"

notify() {
  local msg="$1"
  if [ "$NOTIFY_GOTIFY" = true ]; then
    curl -s -X POST "https://gotify.example.com/message" -d "token=YOUR_GOTIFY_TOKEN&message=$msg" >/dev/null
  fi
  if [ "$NOTIFY_MAILRISE" = true ]; then
    curl -s -X POST "https://mailrise.example.com/send" -d "text=$msg" >/dev/null
  fi
  if [ "$NOTIFY_APPRISE" = true ]; then
    apprise -q -b "Addon Updater" "$msg"
  fi
}

calc_next_run() {
  local min hour
  min=$(echo "$CRON_SCHEDULE" | awk '{print $1}')
  hour=$(echo "$CRON_SCHEDULE" | awk '{print $2}')

  current_ts=$(TZ="$TIMEZONE" date +%s)
  next_run_today=$(TZ="$TIMEZONE" date -d "today $hour:$min" +%s)
  next_run_tomorrow=$(TZ="$TIMEZONE" date -d "tomorrow $hour:$min" +%s)

  if [ "$next_run_today" -gt "$current_ts" ]; then
    diff_sec=$(( next_run_today - current_ts ))
  else
    diff_sec=$(( next_run_tomorrow - current_ts ))
  fi

  hours=$(( diff_sec / 3600 ))
  minutes=$(( (diff_sec % 3600) / 60 ))

  echo "$hours hours $minutes minutes"
}

get_image_version() {
  local file="$1"
  if [ -f "$file" ]; then
    local img ver
    img=$(jq -r '.image // ""' "$file")
    ver=$(jq -r '.version // .upstream_version // ""' "$file")
    echo "$img|$ver"
  else
    echo "|"
  fi
}

get_latest_dockerhub_tag() {
  local image="$1"
  local repo latest_tag tag_json

  repo="${image%%:*}"
  if [[ "$repo" != *"/"* ]]; then
    repo="library/$repo"
  fi

  tag_json=$(curl -s "https://hub.docker.com/v2/repositories/$repo/tags?page_size=100")
  if [ -z "$tag_json" ]; then
    echo ""
    return
  fi

  latest_tag=$(echo "$tag_json" | jq -r '.results[].name' | grep -v -e '^latest$' | sort -rV | head -n1)
  echo "${latest_tag:-latest}"
}

get_latest_linuxserver_tag() {
  # This is a fallback stub, LinuxServer.io doesn’t have an official public API for tags.
  # You can implement scraping or Github release checks if needed.
  echo ""
}

get_latest_github_tag() {
  local image="$1"
  # Placeholder: you can map image names to GitHub repos and fetch latest releases via GitHub API.
  echo ""
}

update_json_version() {
  local file="$1"
  local version="$2"
  local image="$3"
  local slug="$4"
  if [ ! -f "$file" ]; then
    return 1
  fi
  local tmpfile
  tmpfile=$(mktemp)
  jq --arg v "$version" --arg img "$image" --arg slug "$slug" '
    (.version? // .upstream_version?) as $oldver |
    if has("version") then
      .version = $v
    else if has("upstream_version") then
      .upstream_version = $v
    else
      .
    end
    | .image = $img
    | .slug = $slug
  ' "$file" > "$tmpfile" && mv "$tmpfile" "$file"
  return 0
}

update_changelog() {
  local addon_dir="$1"
  local new_version="$2"
  local changelog_url="$3"

  local changelog_file="$addon_dir/CHANGELOG.md"
  local date_str
  date_str=$(date +"%d-%m-%Y")

  if [ ! -f "$changelog_file" ]; then
    echo "v$new_version ($date_str)" > "$changelog_file"
    echo "" >> "$changelog_file"
    echo "Update to version $new_version (changelog: $changelog_url)" >> "$changelog_file"
    log "$COLOR_GREEN" "🆕 Created CHANGELOG.md for $(basename "$addon_dir")"
  else
    echo "" >> "$changelog_file"
    echo "v$new_version ($date_str)" >> "$changelog_file"
    echo "" >> "$changelog_file"
    echo "Update to version $new_version (changelog: $changelog_url)" >> "$changelog_file"
    log "$COLOR_GREEN" "✅ Updated CHANGELOG.md for $(basename "$addon_dir")"
  fi
}

main() {
  log "$COLOR_PURPLE" "🔮 Add-on Updater started"
  log "$COLOR_BLUE" "📅 Cron schedule: $CRON_SCHEDULE (Timezone: $TIMEZONE)"
  local next_run
  next_run=$(calc_next_run)
  log "$COLOR_BLUE" "⏳ Next run in: $next_run"
  log "$COLOR_BLUE" "🏃 Running update check..."

  cd "$GITHUB_REPO"
  git config user.name "$GITHUB_USER"
  git config user.email "$GITHUB_EMAIL"
  if git pull origin main; then
    log "$COLOR_GREEN" "✅ Git pull successful."
  else
    log "$COLOR_RED" "❌ Git pull failed."
    exit 1
  fi

  local updated_any=false
  local notifications=""

  for addon_dir in "$REPO_DIR"/addons/*/; do
    [ -d "$addon_dir" ] || continue
    local slug
    slug=$(basename "$addon_dir")

    local cfg_img_ver build_img_ver upd_img_ver
    cfg_img_ver=$(get_image_version "$addon_dir/config.json")
    build_img_ver=$(get_image_version "$addon_dir/build.json")
    upd_img_ver=$(get_image_version "$addon_dir/updater.json")

    local img version
    img=$(echo -e "$cfg_img_ver\n$build_img_ver\n$upd_img_ver" | grep -m1 -v '^|$' | cut -d '|' -f1)
    version=$(echo -e "$cfg_img_ver\n$build_img_ver\n$upd_img_ver" | grep -m1 -v '^|$' | cut -d '|' -f2)

    if [ -z "$img" ] || [ -z "$version" ]; then
      log "$COLOR_YELLOW" "⚠️ Addon $slug missing image or version, skipping."
      continue
    fi

    log "$COLOR_PURPLE" "🧩 Addon: $slug"
    log "$COLOR_YELLOW" "🔢 Current version: $version"
    log "$COLOR_YELLOW" "📦 Image: $img"

    # Check tags in order: DockerHub > LinuxServer > GitHub
    local latest_tag
    latest_tag=$(get_latest_dockerhub_tag "$img")
    if [ -z "$latest_tag" ]; then
      latest_tag=$(get_latest_linuxserver_tag "$img")
    fi
    if [ -z "$latest_tag" ]; then
      latest_tag=$(get_latest_github_tag "$img")
    fi
    if [ -z "$latest_tag" ]; then
      latest_tag="latest"
      log "$COLOR_YELLOW" "⚠️ No tags found for $slug, defaulting to 'latest'"
    fi

    log "$COLOR_BLUE" "🚀 Latest version: $latest_tag"

    if [ "$latest_tag" != "$version" ]; then
      log "$COLOR_GREEN" "⬆️  Updating $slug from $version to $latest_tag"

      for json_file in "$addon_dir/config.json" "$addon_dir/build.json" "$addon_dir/updater.json"; do
        if [ -f "$json_file" ]; then
          update_json_version "$json_file" "$latest_tag" "$img" "$slug" && \
          log "$COLOR_GREEN" "✅ Updated $json_file"
        fi
      done

      update_changelog "$addon_dir" "$latest_tag" "https://github.com/${slug}/releases"

      updated_any=true
      notifications+="Addon $slug updated from $version to $latest_tag\n"
    else
      log "$COLOR_GREEN" "✔️ $slug is already up to date ($version)"
    fi

    log "$COLOR_BLUE" "----------------------------"
  done

  if $updated_any; then
    git add .
    git commit -m "$GIT_COMMIT_MSG"
    if git push origin main; then
      log "$COLOR_GREEN" "✅ Git push successful."
      notify "Add-on Updater: Updates applied successfully:\n$notifications"
    else
      log "$COLOR_RED" "❌ Git push failed."
    fi
  else
    log "$COLOR_BLUE" "ℹ️ No changes to commit."
  fi

  log "$COLOR_PURPLE" "😴 Add-on Updater finished."
}

main
