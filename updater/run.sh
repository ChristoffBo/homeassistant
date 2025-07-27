#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"
CRON_SCRIPT="/run_update.sh"
CRON_FILE="/etc/crontabs/root"

# Colored output
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"

log() {
  local color="$1"
  shift
  echo -e "${color}[$(TZ="${TZ}" date '+%Y-%m-%d %H:%M:%S %Z')] $*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "❌ ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Load config
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_time // "02:00"' "$CONFIG_PATH")
TZ=$(jq -r '.TZ // "UTC"' "$CONFIG_PATH")

CRON_HOUR="${CHECK_TIME%%:*}"
CRON_MINUTE="${CHECK_TIME##*:}"

mkdir -p /etc/crontabs

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

: > "$LOG_FILE"

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "$COLOR_BLUE" "📥 Cloning repository..."
    git clone "$GIT_AUTH_REPO" "$REPO_DIR"
    log "$COLOR_GREEN" "✅ Repository cloned successfully."
  else
    log "$COLOR_BLUE" "🔄 Pulling latest changes..."
    git -C "$REPO_DIR" pull
    log "$COLOR_GREEN" "✅ Repository updated."
  fi
}

fetch_latest_dockerhub_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100&ordering=last_updated"
  local tags_json
  tags_json=$(curl -s "$url")
  echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | sort -Vr | head -n 1
}

fetch_latest_linuxserver_tag() {
  local repo="$1"
  local url="https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100&ordering=last_updated"
  local tags_json
  tags_json=$(curl -s "$url")
  echo "$tags_json" | jq -r '.results[].name' | grep -v '^latest$' | sort -Vr | head -n 1
}

fetch_latest_ghcr_tag() {
  local image="$1"
  local repo_path="${image#ghcr.io/}"
  local url="https://ghcr.io/v2/${repo_path}/tags/list"
  local tags_json
  tags_json=$(curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" "$url" 2>/dev/null)
  echo "$tags_json" | jq -r '.tags[]?' | grep -v '^latest$' | sort -Vr | head -n 1
}

get_highest_version() {
  local versions=("$@")
  printf '%s\n' "${versions[@]}" | sort -Vr | head -n1
}

get_latest_docker_tag() {
  local image="$1"
  local image_no_tag="${image%%:*}"

  if [[ "$image_no_tag" == lscr.io/linuxserver/* ]]; then
    image_no_tag="${image_no_tag#lscr.io/}"
  fi

  local candidates=()

  if [[ "$image_no_tag" == linuxserver/* ]]; then
    candidates+=( "$(fetch_latest_linuxserver_tag "$image_no_tag")" )
  elif [[ "$image_no_tag" == ghcr.io/* ]]; then
    candidates+=( "$(fetch_latest_ghcr_tag "$image_no_tag")" )
  else
    candidates+=( "$(fetch_latest_dockerhub_tag "$image_no_tag")" )
  fi

  if [[ "$image_no_tag" == linuxserver/* ]]; then
    local plain_repo="${image_no_tag#linuxserver/}"
    candidates+=( "$(fetch_latest_dockerhub_tag "linuxserver/$plain_repo")" )
    candidates+=( "$(fetch_latest_ghcr_tag "linuxserver/$plain_repo")" )
  fi

  local filtered=()
  for v in "${candidates[@]}"; do
    if [[ -n "$v" && "$v" != "null" ]]; then
      filtered+=( "$v" )
    fi
  done

  if [ ${#filtered[@]} -eq 0 ]; then
    echo "latest"
  else
    get_highest_version "${filtered[@]}"
  fi
}

update_addon_if_needed() {
  local addon_dir="$1"
  local config_file="$addon_dir/config.json"
  local updater_file="$addon_dir/updater.json"
  local changelog_file="$addon_dir/CHANGELOG.md"

  [ ! -f "$config_file" ] && return

  local image
  image=$(jq -r '.image // empty' "$config_file")
  [ -z "$image" ] && return

  local current_version
  current_version=$(jq -r '.version // ""' "$config_file")
  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  log "$COLOR_BLUE" "----------------------------"
  log "$COLOR_BLUE" "🧩 Addon: $(basename "$addon_dir")"
  log "$COLOR_BLUE" "🔢 Current version: $current_version"
  log "$COLOR_BLUE" "🚀 Latest version: $latest_version"

  if [ "$latest_version" != "" ] && [ "$latest_version" != "$current_version" ] && [ "$latest_version" != "null" ]; then
    log "$COLOR_YELLOW" "⬆️  Updating $(basename "$addon_dir") from $current_version to $latest_version"

    # Update version tag only in config.json
    jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    # Update updater.json metadata
    jq -n --arg slug "$(basename "$addon_dir")" --arg image "$image" --arg v "$latest_version" --arg dt "$(TZ="$TZ" date '+%d-%m-%Y %H:%M')" \
      '{slug: $slug, image: $image, upstream_version: $v, last_update: $dt}' > "$updater_file"

    # Create changelog if missing
    if [ ! -f "$changelog_file" ]; then
      echo "CHANGELOG for $(basename "$addon_dir")" > "$changelog_file"
      echo "===================" >> "$changelog_file"
      log "$COLOR_YELLOW" "📝 Created new CHANGELOG.md for $(basename "$addon_dir")"
    fi

    # Add only version tag entry to changelog (prepend)
    NEW_ENTRY="v$latest_version ($(TZ="$TZ" date '+%d-%m-%Y %H:%M'))"

    { head -n 2 "$changelog_file"; echo "$NEW_ENTRY"; echo ""; tail -n +3 "$changelog_file"; } > "$changelog_file.tmp" && mv "$changelog_file.tmp" "$changelog_file"

    log "$COLOR_GREEN" "✅ CHANGELOG.md updated for $(basename "$addon_dir")"

    # Commit & push only this addon's directory and changelog
    git -C "$REPO_DIR" add "$addon_dir"
    git -C "$REPO_DIR" commit -m "⬆️ Update addon $(basename "$addon_dir") to $latest_version" || true
    git -C "$REPO_DIR" push

  else
    log "$COLOR_GREEN" "✔️ $(basename "$addon_dir") is already up to date ($current_version)"
  fi
  log "$COLOR_BLUE" "----------------------------"
}

perform_update_check() {
  clone_or_update_repo

  for addon in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon"
  done
}

# Create cron-executed script
cat <<EOF > "$CRON_SCRIPT"
#!/usr/bin/env bash
export TZ="$TZ"
$(declare -f log)
$(declare -f clone_or_update_repo)
$(declare -f fetch_latest_dockerhub_tag)
$(declare -f fetch_latest_linuxserver_tag)
$(declare -f fetch_latest_ghcr_tag)
$(declare -f get_highest_version)
$(declare -f get_latest_docker_tag)
$(declare -f update_addon_if_needed)
$(declare -f perform_update_check)

log "\$COLOR_GREEN" "⏰ Cron triggered update at \$(TZ=\"$TZ\" date)"
perform_update_check
EOF

chmod +x "$CRON_SCRIPT"

echo "$CRON_MINUTE $CRON_HOUR * * * root $CRON_SCRIPT >> $LOG_FILE 2>&1" > "$CRON_FILE"

log "$COLOR_GREEN" "🚀 Add-on Updater initialized"
log "$COLOR_YELLOW" "📅 Scheduled daily at $CHECK_TIME ($TZ)"

log "$COLOR_GREEN" "🏃 Running initial update check on startup..."
perform_update_check

log "$COLOR_BLUE" "⏳ Waiting for cron to trigger..."

crond -f -L /dev/stdout
