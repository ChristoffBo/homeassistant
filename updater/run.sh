#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}$*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time' "$CONFIG_PATH")  # Format HH:MM

GITHUB_AUTH_HEADER=""
if [ -n "$GITHUB_TOKEN" ]; then
  GITHUB_AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"
fi

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR" ]; then
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR"
    else
      git clone "$GITHUB_REPO" "$REPO_DIR"
    fi
  else
    cd "$REPO_DIR"
    git pull
  fi
}

# Fetch functions unchanged, omitted here for brevity (keep your existing functions)

update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local build_file="$addon_path/build.json"
  local changelog_file="$addon_path/CHANGELOG.md"

  if [ ! -f "$config_file" ] && [ ! -f "$build_file" ]; then
    # No config or build file: skip silently
    return 1
  fi

  local image=""

  if [ -f "$build_file" ]; then
    local arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then arch="amd64"; fi
    image=$(jq -r --arg arch "$arch" '.build_from[$arch] // .build_from.amd64 // .build_from | select(type=="string")' "$build_file")
  fi

  if [ -z "$image" ] && [ -f "$config_file" ]; then
    image=$(jq -r '.image // empty' "$config_file")
  fi

  if [ -z "$image" ] || [ "$image" == "null" ]; then
    return 1
  fi

  local slug
  slug=$(jq -r '.slug // empty' "$config_file")
  if [ -z "$slug" ] || [ "$slug" == "null" ]; then
    slug=$(basename "$addon_path")
  fi

  local upstream_version=""
  if [ -f "$updater_file" ]; then
    upstream_version=$(jq -r '.upstream_version // empty' "$updater_file")
  fi

  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ]; then
    return 1
  fi

  if [ "$latest_version" != "$upstream_version" ]; then
    jq --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" 2>/dev/null || \
      jq -n --arg slug "$slug" --arg image "$image" --arg v "$latest_version" --arg dt "$(date +'%d-%m-%Y %H:%M')" \
        '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file.tmp"

    mv "$updater_file.tmp" "$updater_file"

    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" 2>/dev/null || true

    if [ -f "$config_file.tmp" ]; then
      mv "$config_file.tmp" "$config_file"
    fi

    if [ ! -f "$changelog_file" ]; then
      touch "$changelog_file"
    fi

    {
      echo "v$latest_version ($(date +'%d-%m-%Y %H:%M'))"
      echo ""
      echo "    Update to latest version from $image"
      echo ""
    } >> "$changelog_file"

    return 0  # Indicate update performed
  fi

  return 1  # No update
}

perform_update_check() {
  clone_or_update_repo

  local total=0
  local updated=0

  for addon_path in "$REPO_DIR"/*/; do
    ((total++))
    if update_addon_if_needed "$addon_path"; then
      ((updated++))
    fi
  done

  echo "$total" "$updated"
}

LAST_RUN_FILE="/data/last_run_date.txt"

log "$COLOR_GREEN" "🚀 HomeAssistant Addon Updater started at $(date '+%d-%m-%Y %H:%M')"

while true; do
  NOW_TIME=$(date +%H:%M)
  TODAY=$(date +%Y-%m-%d)
  LAST_RUN=""

  if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
  fi

  if [ "$NOW_TIME" = "$CHECK_TIME" ] && [ "$LAST_RUN" != "$TODAY" ]; then
    log "$COLOR_GREEN" "Updating..."

    read total updated < <(perform_update_check)

    log "$COLOR_GREEN" "Checked $total addons, updated $updated addons."

    echo "$TODAY" > "$LAST_RUN_FILE"
    log "$COLOR_GREEN" "✅ Scheduled update checks complete."
  else
    CURRENT_SEC=$(date +%s)
    CHECK_SEC=$(date -d "$CHECK_TIME" +%s 2>/dev/null || echo 0)

    if [ "$CURRENT_SEC" -ge "$CHECK_SEC" ]; then
      NEXT_CHECK_TIME=$(date -d "tomorrow $CHECK_TIME" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
    else
      NEXT_CHECK_TIME=$(date -d "today $CHECK_TIME" '+%H:%M %d-%m-%Y' 2>/dev/null || echo "$CHECK_TIME (unknown)")
    fi

    log "$COLOR_BLUE" "📅 Next check scheduled at $NEXT_CHECK_TIME"
  fi

  sleep 60
done
