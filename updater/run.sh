#!/bin/bash

set -e

ADDONS_DIR="/addons"
NOW=$(date +"%d-%m-%Y %H:%M")
CONFIG_FILE="/data/options.json"
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_FILE")
GOTIFY_URL=$(jq -r '.gotify_url' "$CONFIG_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token' "$CONFIG_FILE")
MAILRISE_URL=$(jq -r '.mailrise_url' "$CONFIG_FILE")

log_info() {
  echo -e "\033[1;36m$1\033[0m"
}

log_success() {
  echo -e "\033[1;32m$1 ✔\033[0m"
}

log_warning() {
  echo -e "\033[1;33m$1\033[0m"
}

log_update() {
  echo -e "\033[1;32m$1 🟢\033[0m"
}

log_up_to_date() {
  echo -e "\033[1;34m$1 🔵\033[0m"
}

send_notification() {
  local message="$1"

  if [[ -n "$GOTIFY_URL" && -n "$GOTIFY_TOKEN" ]]; then
    curl -s -X POST "$GOTIFY_URL/message" \
      -F "token=$GOTIFY_TOKEN" \
      -F "title=Addon Updater" \
      -F "message=$message" > /dev/null
  fi

  if [[ -n "$MAILRISE_URL" ]]; then
    curl -s -X POST "$MAILRISE_URL" -d "$message" > /dev/null
  fi
}

get_latest_tag() {
  local repo_url="$1"
  local retries=5
  local delay=2

  for ((i=1; i<=retries; i++)); do
    local result
    result=$(curl -s --retry 0 "https://hub.docker.com/v2/repositories/${repo_url}/tags?page_size=1&page=1&ordering=last_updated")

    if [[ -z "$result" || "$result" == "null" ]]; then
      log_warning "Attempt $i: Failed to fetch tags from DockerHub for $repo_url. Retrying in ${delay}s..."
      sleep $delay
      delay=$((delay * 2))
    else
      echo "$result" | jq -r '.results[0].name'
      return
    fi
  done

  echo ""
}

update_addon() {
  local addon_path="$1"
  local config_path="$addon_path/config.json"
  local updater_path="$addon_path/updater.json"

  if [[ ! -f "$config_path" ]]; then
    return
  fi

  local name=$(jq -r '.name' "$config_path")
  local version=$(jq -r '.version' "$config_path")
  local image=$(jq -r '.image // empty' "$config_path")
  local slug=$(jq -r '.slug // empty' "$config_path")

  if [[ -z "$image" ]]; then
    log_warning "Skipping '$name' – No Docker image defined"
    return
  fi

  # Ensure updater.json exists
  if [[ ! -f "$updater_path" ]]; then
    echo "{\"last_update\": \"$NOW\"}" > "$updater_path"
  fi

  latest_tag=$(get_latest_tag "$image")

  if [[ -z "$latest_tag" || "$latest_tag" == "null" ]]; then
    log_warning "Addon: $slug"
    log_warning "Could not fetch latest tag for image $image"
    echo "----------------------------"
    return
  fi

  last_update=$(jq -r '.last_update' "$updater_path" 2>/dev/null)

  log_info "Addon: $slug"
  log_warning "Last updated: ${last_update:-Never}"
  log_info "Current Docker version: $version"
  log_info "Latest Docker version:  $latest_tag"

  if [[ "$version" != "$latest_tag" ]]; then
    jq --arg v "$latest_tag" '.version = $v' "$config_path" > "$config_path.tmp" && mv "$config_path.tmp" "$config_path"
    echo "{\"last_update\": \"$NOW\"}" > "$updater_path"
    log_update "Addon '$slug' updated to version $latest_tag"
    send_notification "Addon '$slug' updated to version $latest_tag"
  else
    log_up_to_date "Addon '$slug' is already up-to-date"
  fi
  echo "----------------------------"
}

log_info "🚀 HomeAssistant Addon Updater started at $NOW"
send_notification "HomeAssistant Addon Startup Notification"

for addon in "$ADDONS_DIR"/*; do
  [ -d "$addon" ] && update_addon "$addon"
done

log_info "Next check scheduled at $CHECK_TIME tomorrow"
