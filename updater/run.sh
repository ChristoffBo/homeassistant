#!/usr/bin/with-contenv bash
set -e

ADDONS_DIR="/data/addons/local"
CONFIG_FILE="/data/options.json"

# Load config
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_FILE")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_FILE")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_FILE")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_FILE")
GOTIFY_URL=$(jq -r '.gotify_url' "$CONFIG_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token' "$CONFIG_FILE")
MAILRISE_URL=$(jq -r '.mailrise_url' "$CONFIG_FILE")

log_info() {
  echo -e "\033[1;32m$1\033[0m"
}

log_warn() {
  echo -e "\033[1;33m$1\033[0m"
}

send_notification() {
  local message="$1"

  if [[ -n "$GOTIFY_URL" && -n "$GOTIFY_TOKEN" ]]; then
    curl -s -X POST "$GOTIFY_URL/message" \
      -F "token=$GOTIFY_TOKEN" \
      -F "title=Addon Updater" \
      -F "message=$message" > /dev/null || true
  fi

  if [[ -n "$MAILRISE_URL" ]]; then
    curl -s -X POST "$MAILRISE_URL" -d "$message" > /dev/null || true
  fi
}

get_latest_tag() {
  local repo="$1"
  local retries=5
  local delay=5

  for ((i=1; i<=retries; i++)); do
    TAG=$(curl -s "https://hub.docker.com/v2/repositories/${repo}/tags?page_size=1&page=1&ordering=last_updated" | jq -r '.results[0].name')
    if [[ -n "$TAG" && "$TAG" != "null" ]]; then
      echo "$TAG"
      return 0
    fi
    sleep $delay
  done

  echo "ERROR"
  return 1
}

update_addon() {
  local addon_path="$1"
  local config="$addon_path/config.json"

  if [[ ! -f "$config" ]]; then return; fi

  local slug
  slug=$(jq -r '.slug // "unknown"' "$config")
  local upstream
  upstream=$(jq -r '.upstream // empty' "$config")

  log_info "----------------------------"
  log_info "Addon: $slug"

  if [[ -z "$upstream" ]]; then
    log_warn "⚠️ No upstream field in addon '$slug' — skipping update logic"
    return
  fi

  local updater_json="$addon_path/updater.json"
  local last_update="never"
  local current_version="unknown"

  if [[ -f "$updater_json" ]]; then
    last_update=$(jq -r '.last_update // "never"' "$updater_json")
    current_version=$(jq -r '.current_version // "unknown"' "$updater_json")
  else
    echo '{}' > "$updater_json"
  fi

  log_info "Last updated: \033[1;33m$last_update\033[0m"
  log_info "Current Docker version: $current_version"

  latest_tag=$(get_latest_tag "$upstream")
  if [[ "$latest_tag" == "ERROR" ]]; then
    log_warn "❌ Could not fetch latest docker tag for repo $upstream"
    return
  fi

  log_info "Latest Docker version:  $latest_tag"

  if [[ "$latest_tag" == "$current_version" ]]; then
    log_info "✅ Addon '$slug' is already up-to-date"
  else
    log_info "🔄 Updating addon '$slug' to version $latest_tag"

    jq --arg ver "$latest_tag" '.version = $ver' "$config" > "$config.tmp" && mv "$config.tmp" "$config"

    jq --arg date "$(date '+%d-%m-%Y')" --arg ver "$latest_tag" \
      '.last_update = $date | .current_version = $ver' "$updater_json" > "$updater_json.tmp" && mv "$updater_json.tmp" "$updater_json"

    echo -e "\n## v$latest_tag ($(date '+%d-%m-%Y'))\n\nUpdated to docker image tag $latest_tag\n" >> "$addon_path/CHANGELOG.md"

    cd "$ADDONS_DIR"
    git config --global user.email "updater@addon.local"
    git config --global user.name "AddonUpdater"
    git add "$slug/config.json" "$slug/updater.json" "$slug/CHANGELOG.md"
    git commit -m "🔄 Update $slug to $latest_tag"
    git push "https://$GITHUB_USERNAME:$GITHUB_TOKEN@github.com/$GITHUB_REPO" HEAD:main

    log_info "✅ Addon '$slug' updated successfully"
    send_notification "✅ Addon '$slug' updated to version $latest_tag"
  fi
}

now=$(date "+%d-%m-%Y %H:%M")
log_info "🚀 HomeAssistant Addon Updater started at $now"
send_notification "🚀 Addon Updater started at $now"

# Run first check immediately
for addon in "$ADDONS_DIR"/*; do
  [ -d "$addon" ] && update_addon "$addon"
done

log_info "📅 Next check scheduled at $CHECK_TIME tomorrow"

# Main loop
while true; do
  current_time=$(date +%H:%M)
  if [[ "$current_time" == "$CHECK_TIME" ]]; then
    log_info "⏰ Running scheduled update at $current_time"
    for addon in "$ADDONS_DIR"/*; do
      [ -d "$addon" ] && update_addon "$addon"
    done
    log_info "📅 Next check scheduled at $CHECK_TIME tomorrow"
    sleep 3600
  else
    sleep 60
  fi
done
