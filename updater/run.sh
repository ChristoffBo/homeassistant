#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
TZ=$(jq -r '.timezone // "Africa/Johannesburg"' "$CONFIG_PATH")
export TZ

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "[\033[0;35m$(TZ=$TZ date -u '+%Y-%m-%d %H:%M:%S %Z')\033[0m] $color$*$COLOR_RESET" | tee -a "$LOG_FILE"
}

notify() {
  local message="$1"
  local title="${2:-"Addon Updater"}"
  local gotify_url=$(jq -r '.notifier.gotify_url // empty' "$CONFIG_PATH")
  local apprise_url=$(jq -r '.notifier.apprise_url // empty' "$CONFIG_PATH")
  local mailrise_url=$(jq -r '.notifier.mailrise_url // empty' "$CONFIG_PATH")

  if [[ -n "$gotify_url" ]]; then
    curl -s -X POST "$gotify_url" -F "title=$title" -F "message=$message" -F "priority=5" >/dev/null || true
  fi

  if [[ -n "$mailrise_url" ]]; then
    curl -s -X POST "$mailrise_url" -H "Content-Type: text/plain" -d "$title: $message" >/dev/null || true
  fi

  if [[ -n "$apprise_url" ]]; then
    curl -s "$apprise_url" -X POST -d "title=$title&body=$message" >/dev/null || true
  fi
}

pull_latest() {
  cd "$REPO_DIR"
  log "$COLOR_BLUE" "🔄 Pulling latest changes from GitHub with rebase..."
  if [ -d .git/rebase-merge ]; then
    log "$COLOR_YELLOW" "⚠️ Detected unfinished rebase, aborting it first..."
    git rebase --abort || rm -rf .git/rebase-merge
  fi
  git reset --hard HEAD
  if ! git pull --rebase; then
    log "$COLOR_RED" "❌ Git pull failed even after aborting rebase. See last 20 log lines below:"
    tail -n 20 "$LOG_FILE"
    return 1
  fi
}

main() {
  log "$COLOR_PURPLE" "🚀 Add-on Updater initialized"
  cron_schedule=$(jq -r '.check_time // "0 3 * * *"' "$CONFIG_PATH")
  log "$COLOR_YELLOW" "📅 Scheduled cron: $cron_schedule (Timezone: $TZ)"
  log "$COLOR_BLUE" "🏃 Running initial update check on startup..."

  pull_latest || return 1

  updated_files=()
  updated_addons=()

  for addon_dir in "$REPO_DIR"/*/; do
    [ -d "$addon_dir" ] || continue
    addon_slug=$(basename "$addon_dir")
    config_file="$addon_dir/config.json"
    build_file="$addon_dir/build.json"
    updater_file="$addon_dir/updater.json"
    changelog_file="$addon_dir/CHANGELOG.md"

    [ -f "$config_file" ] || continue
    image=$(jq -r '.image // empty' "$config_file")
    version=$(jq -r '.version // "unknown"' "$config_file")
    repo_url="https://hub.docker.com/r/${image}"

    log "$COLOR_BLUE" "----------------------------"
    log "$COLOR_BLUE" "🧩 Addon: $addon_slug"
    log "$COLOR_BLUE" "🔢 Current version: $version"
    log "$COLOR_BLUE" "📦 Image: $image"

    # Check for new tag
    tags=$(curl -s "https://hub.docker.com/v2/repositories/${image}/tags/?page_size=100" | jq -r '.results[].name' | grep -E '^[0-9]+\.[0-9]+(\.[0-9]+)?$' | sort -Vr)
    latest_tag=$(echo "$tags" | head -n 1)

    if [[ "$latest_tag" != "$version" && -n "$latest_tag" ]]; then
      log "$COLOR_GREEN" "⬆️ Update available: $version → $latest_tag"

      # Update version
      jq --arg v "$latest_tag" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
      updated_files+=("$config_file")
      updated_addons+=("$addon_slug")

      # Update CHANGELOG.md
      if [[ ! -f "$changelog_file" ]]; then
        echo "# Changelog for $addon_slug" > "$changelog_file"
        echo "" >> "$changelog_file"
      fi

      {
        echo "## $latest_tag - $(date '+%Y-%m-%d')"
        echo "- Updated Docker image to [$latest_tag]($repo_url)"
        echo ""
      } >> "$changelog_file"
      updated_files+=("$changelog_file")

      # Also update build.json and updater.json if exists
      for f in "$build_file" "$updater_file"; do
        [ -f "$f" ] || continue
        jq --arg v "$latest_tag" '.version = $v' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
        updated_files+=("$f")
      fi
    else
      log "$COLOR_GREEN" "✔️ $addon_slug is already up to date ($version)"
    fi
  done

  if (( ${#updated_addons[@]} > 0 )); then
    cd "$REPO_DIR"
    git config --global user.email "addon-updater@local"
    git config --global user.name "Addon Updater"
    git add .
    git commit -m "⬆️ Update addon versions"
    git push || log "$COLOR_RED" "❌ Git push failed. Manual intervention needed."

    notify "Updated addons: ${updated_addons[*]}" "✅ Add-ons Updated"

    if (( ${#updated_files[@]} > 0 )); then
      notify "Created/Updated files:\n${updated_files[*]}" "📁 Files Updated"
    fi
  fi

  # Show next cron time (day, hour, minute)
  next_run=$(crond -l 0 -c /etc/crontabs 2>/dev/null | awk -v tz="$TZ" -v schedule="$cron_schedule" '
    BEGIN {
      split(schedule, s, " ")
      now = systime()
      for (i=0; i<1440; i++) {
        t = now + i*60
        split(strftime("%M %H %d", t, tz), curr, " ")
        if ((s[0]=="*" || s[0]==curr[1]) &&
            (s[1]=="*" || s[1]==curr[2]) &&
            (s[2]=="*" || s[2]==curr[3])) {
          print curr[3] " " curr[2] ":" curr[1]
          exit
        }
      }
    }
  ')
  log "$COLOR_PURPLE" "📆 Next scheduled run: $next_run"
}

main

log "$COLOR_BLUE" "⏳ Waiting for cron to trigger..."
crond -f -d 8 -c /etc/crontabs
