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
COLOR_PURPLE="\033[0;35m"

log() {
  local color="$1"
  shift
  echo -e "${color}[$(TZ="${TZ}" date '+%Y-%m-%d %H:%M:%S %Z')] $*${COLOR_RESET}"
}

if [ ! -f "$CONFIG_PATH" ]; then
  log "$COLOR_RED" "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Load config options
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
CHECK_TIME=$(jq -r '.check_cron // "02:00"' "$CONFIG_PATH")
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
    if git clone "$GIT_AUTH_REPO" "$REPO_DIR"; then
      log "$COLOR_GREEN" "✅ Repository cloned successfully."
    else
      log "$COLOR_RED" "❌ Failed to clone repository!"
      exit 1
    fi
  else
    log "$COLOR_BLUE" "🔄 Pulling latest changes from GitHub..."
    if git -C "$REPO_DIR" pull; then
      log "$COLOR_GREEN" "✅ Git pull successful."
    else
      log "$COLOR_RED" "❌ Git pull failed!"
      exit 1
    fi
  fi
}

fetch_latest_dockerhub_tag() {
  local image="$1"
  curl -s "https://registry.hub.docker.com/v1/repositories/$image/tags" | jq -r '.[].name' | grep -v latest | sort -Vr | head -n1
}

fetch_latest_linuxserver_tag() {
  local image="$1"
  curl -s "https://hub.docker.com/v2/repositories/linuxserver/$image/tags?page_size=100" |
    jq -r '.results[].name' | grep -v latest | sort -Vr | head -n1
}

fetch_latest_ghcr_tag() {
  local image="$1"
  curl -s -H "Accept: application/vnd.github.v3+json" "https://ghcr.io/v2/$image/tags/list" |
    jq -r '.tags[]' | grep -v latest | sort -Vr | head -n1
}

get_latest_docker_tag() {
  local image="$1"
  if [[ "$image" == ghcr.io/* ]]; then
    fetch_latest_ghcr_tag "${image#ghcr.io/}"
  elif [[ "$image" == linuxserver/* ]]; then
    fetch_latest_linuxserver_tag "${image#linuxserver/}"
  else
    fetch_latest_dockerhub_tag "$image"
  fi
}

update_addon_if_needed() {
  local addon_dir="$1"
  local config_file="$addon_dir/config.json"
  local updater_file="$addon_dir/updater.json"

  [ ! -f "$config_file" ] && return
  [ ! -f "$updater_file" ] && return

  local image
  image=$(jq -r '.image // empty' "$config_file")
  [ -z "$image" ] && return

  local current_version
  current_version=$(jq -r '.version // ""' "$config_file")
  local latest_version
  latest_version=$(get_latest_docker_tag "$image")

  if [ -z "$latest_version" ]; then
    log "$COLOR_YELLOW" "⚠️ Could not fetch latest version for $(basename "$addon_dir")"
    return
  fi

  if [ "$current_version" != "$latest_version" ]; then
    log "$COLOR_YELLOW" "⬆️  Updating $(basename "$addon_dir") from $current_version to $latest_version"
    jq ".version = \"$latest_version\"" "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"

    local changelog_file="$addon_dir/CHANGELOG.md"
    local change_date
    change_date=$(TZ="$TZ" date '+%d-%m-%Y')

    local docker_url
    if [[ "$image" == ghcr.io/* ]]; then
      docker_url="https://github.com/${image#ghcr.io/}"
    elif [[ "$image" == linuxserver/* ]]; then
      docker_url="https://github.com/linuxserver/docker-${image#linuxserver/}"
    else
      docker_url="https://hub.docker.com/r/$image"
    fi

    if [ ! -f "$changelog_file" ]; then
      echo "# Changelog for $(basename "$addon_dir")" > "$changelog_file"
      log "$COLOR_BLUE" "🆕 Created CHANGELOG.md for $(basename "$addon_dir")"
    fi

    echo -e "\nv${latest_version} (${change_date})\n\n    Update to latest version from $docker_url" >> "$changelog_file"

    echo "{\"last_update\": \"$change_date\"}" > "$updater_file"
    UPDATED=true
  else
    local last_update
    last_update=$(jq -r '.last_update // "N/A"' "$updater_file")
    log "$COLOR_GREEN" "✅ $(basename "$addon_dir") is already up to date ($current_version)"
    log "$COLOR_GREEN" "🕒 Last updated: $last_update"
  fi
}

perform_update_check() {
  UPDATED=false
  clone_or_update_repo

  log "$COLOR_PURPLE" "🔍 Checking add-ons in $REPO_DIR..."

  for addon in "$REPO_DIR"/*/; do
    update_addon_if_needed "$addon"
  done

  if $UPDATED; then
    log "$COLOR_BLUE" "🚀 Committing and pushing updates..."
    git -C "$REPO_DIR" config user.email "addon-updater@local"
    git -C "$REPO_DIR" config user.name "Addon Updater"
    git -C "$REPO_DIR" add .
    git -C "$REPO_DIR" commit -m "chore: update add-ons automatically"
    git -C "$REPO_DIR" push
    log "$COLOR_GREEN" "✅ Updates pushed to GitHub."
  else
    log "$COLOR_GREEN" "🟢 No updates found."
  fi
}

# Create cron script
cat <<EOF > "$CRON_SCRIPT"
#!/usr/bin/env bash
export TZ="$TZ"
CONFIG_PATH="$CONFIG_PATH"
REPO_DIR="$REPO_DIR"
LOG_FILE="$LOG_FILE"
GITHUB_REPO="$GITHUB_REPO"
GIT_AUTH_REPO="$GIT_AUTH_REPO"
GITHUB_USERNAME="$GITHUB_USERNAME"
GITHUB_TOKEN="$GITHUB_TOKEN"

$(declare -f log)
$(declare -f clone_or_update_repo)
$(declare -f fetch_latest_dockerhub_tag)
$(declare -f fetch_latest_linuxserver_tag)
$(declare -f fetch_latest_ghcr_tag)
$(declare -f get_latest_docker_tag)
$(declare -f update_addon_if_needed)
$(declare -f perform_update_check)

log "\$COLOR_GREEN" "⏰ Cron triggered update at \$(TZ=\"$TZ\" date)"
perform_update_check
EOF

chmod +x "$CRON_SCRIPT"
echo "$CRON_MINUTE $CRON_HOUR * * * root $CRON_SCRIPT >> /dev/stdout 2>&1" > "$CRON_FILE"

# Calculate next run time in a portable way
NEXT_RUN_DATE=$(TZ="$TZ" date -d "+1 day" +%Y-%m-%d)
NEXT_RUN="$NEXT_RUN_DATE $CHECK_TIME $TZ"

log "$COLOR_BLUE" "⏳ Waiting for cron to trigger at $NEXT_RUN"
crond -f -L /dev/stdout
