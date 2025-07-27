#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

# Load config options
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
CRON_SCHEDULE=$(jq -r '.cron // "* * * * *"' "$CONFIG_PATH")
NOTIFIER_TYPE=$(jq -r '.notifier.type // empty' "$CONFIG_PATH")
NOTIFIER_URL=$(jq -r '.notifier.url // empty' "$CONFIG_PATH")
NOTIFIER_TOKEN=$(jq -r '.notifier.token // empty' "$CONFIG_PATH")

export TZ="$TIMEZONE"

# Colors for logs
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  echo -e "[\033[90m$(date '+%Y-%m-%d %H:%M:%S %Z')\033[0m] ${color}$*${COLOR_RESET}" | tee -a "$LOG_FILE"
}

send_notification() {
  local message="$1"

  if [[ -z "$NOTIFIER_TYPE" || -z "$NOTIFIER_URL" ]]; then
    log "$COLOR_YELLOW" "⚠️ Notifier not configured, skipping notification."
    return
  fi

  case "$NOTIFIER_TYPE" in
    gotify)
      curl -s -X POST "$NOTIFIER_URL/message" \
        -H "X-Gotify-Key: $NOTIFIER_TOKEN" \
        -F "title=Addon Updater" \
        -F "message=$message" \
        -F "priority=5" > /dev/null || true
      ;;
    mailrise)
      curl -s -X POST "$NOTIFIER_URL" -H "Content-Type: text/plain" --data "$message" > /dev/null || true
      ;;
    apprise)
      curl -s "$NOTIFIER_URL" -d "$message" > /dev/null || true
      ;;
    *)
      log "$COLOR_RED" "❌ Unknown notifier type: $NOTIFIER_TYPE"
      ;;
  esac
}

# The actual update check and apply logic
update_addons() {
  UPDATED=0
  UPDATE_SUMMARY=""

  cd "$REPO_DIR"

  for addon_path in */; do
    config_file="$addon_path/config.json"
    build_file="$addon_path/build.json"
    updater_file="$addon_path/updater.json"

    if [[ ! -f "$config_file" && ! -f "$build_file" && ! -f "$updater_file" ]]; then
      log "$COLOR_YELLOW" "⚠️ Add-on '$addon_path' missing config/build/updater JSON, skipping."
      continue
    fi

    image=""
    current_version=""

    if [[ -f "$config_file" ]]; then
      image=$(jq -r '.image // empty' "$config_file")
      current_version=$(jq -r '.version // empty' "$config_file")
    fi

    if [[ -z "$image" || "$image" == "null" ]]; then
      if [[ -f "$build_file" ]]; then
        arch=$(uname -m)
        [[ "$arch" == "x86_64" ]] && arch="amd64"
        image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from // empty' "$build_file")
        [[ -z "$current_version" || "$current_version" == "null" ]] && current_version=$(jq -r '.version // empty' "$build_file")
      fi
    fi

    if [[ -z "$current_version" || "$current_version" == "null" ]]; then
      if [[ -f "$updater_file" ]]; then
        current_version=$(jq -r '.version // empty' "$updater_file")
      fi
    fi

    slug=$(jq -r '.slug // empty' "$config_file" 2>/dev/null)
    if [[ -z "$slug" ]]; then
      slug="${addon_path%/}"
    fi

    log "$COLOR_PURPLE" "\n🧩 Addon: $slug"
    log "$COLOR_BLUE" "🔢 Current version: $current_version"
    log "$COLOR_BLUE" "📦 Image: $image"

    if [[ "$image" == *":"* ]]; then
      repo="${image%:*}"
      tag="${image##*:}"
    else
      repo="$image"
      tag="latest"
    fi

    norm_current_version=$(echo "$current_version" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')
    norm_tag=$(echo "$tag" | sed -E 's/^(amd64|armhf|arm64|aarch64|x86_64|armv7)-//')

    if [[ "$norm_tag" == "latest" || "$norm_tag" == *"latest"* ]]; then
      log "$COLOR_YELLOW" "⚠️ Skipping add-on '$slug' because Docker tag '$tag' is unsupported."
      log "$COLOR_BLUE" "----------------------------"
      continue
    fi

    api_repo="$repo"
    api_repo="${api_repo#lscr.io/}"

    tags_json=$(curl -s "https://hub.docker.com/v2/repositories/$api_repo/tags?page_size=100" || echo "{}")
    tags=$(echo "$tags_json" | jq -r '.results[].name' 2>/dev/null || echo "")

    filtered_tags=$(echo "$tags" | grep -v -E 'latest|rc' || true)
    latest_tag=$(echo "$filtered_tags" | sort -Vr | head -n1)

    if [[ -z "$latest_tag" ]]; then
      log "$COLOR_RED" "❌ Could not fetch tags for $repo"
      log "$COLOR_BLUE" "----------------------------"
      continue
    fi

    log "$COLOR_GREEN" "🚀 Latest version: $latest_tag"
    log "$COLOR_GREEN" "🕒 Last updated: $(date '+%d-%m-%Y %H:%M')"

    if [[ "$norm_current_version" != "$latest_tag" ]]; then
      log "$COLOR_YELLOW" "⬆️  Updating $slug from $current_version to $latest_tag"

      if [[ -f "$config_file" ]]; then
        jq --arg v "$latest_tag" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
      fi

      if [[ -f "$build_file" ]]; then
        jq --arg v "$latest_tag" '.version = $v' "$build_file" > "$build_file.tmp" && mv "$build_file.tmp" "$build_file"
      fi

      if [[ -f "$updater_file" ]]; then
        jq --arg v "$latest_tag" --arg dt "$(date '+%d-%m-%Y %H:%M')" '.version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"
      else
        echo "{\"version\": \"$latest_tag\", \"last_update\": \"$(date '+%d-%m-%Y %H:%M')\"}" > "$updater_file"
      fi

      changelog="$addon_path/CHANGELOG.md"
      if [[ ! -f "$changelog" ]]; then
        echo "# CHANGELOG for $slug" > "$changelog"
        echo "" >> "$changelog"
      fi
      echo -e "\n## $latest_tag - $(date '+%Y-%m-%d %H:%M:%S')\n- Updated Docker tag from \`$tag\` to \`$latest_tag\`" >> "$changelog"
      log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $slug"

      UPDATED=1
      UPDATE_SUMMARY+="\n🔧 $slug updated from $current_version → $latest_tag"
    else
      log "$COLOR_GREEN" "✔️ $slug is already up to date ($current_version)"
    fi

    log "$COLOR_BLUE" "----------------------------"
  done

  if [[ $UPDATED -eq 1 ]]; then
    send_notification "📦 Add-ons updated:$UPDATE_SUMMARY"
  else
    log "$COLOR_GREEN" "✅ No updates needed."
  fi
}

# Run update on script start
update_addons

# Start cron with configured schedule
echo "$CRON_SCHEDULE /bin/bash /usr/local/bin/run.sh" > /etc/crontabs/root
crond -f -L /var/log/cron.log
