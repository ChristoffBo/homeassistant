#!/bin/bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"
CHANGELOG_FILE="CHANGELOG.md"

# ======================
# COLOR DEFINITIONS
# ======================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_CYAN="\033[0;36m"

# ======================
# GLOBAL VARIABLES
# ======================
declare -A UPDATED_ADDONS
declare -A UNCHANGED_ADDONS
declare -a SKIP_LIST=()

safe_jq() {
  local expr="$1"
  local file="$2"
  jq -e -r "$expr" "$file" 2>/dev/null | grep -E '^[[:alnum:]][[:alnum:].:_-]*$' || echo "unknown"
}

read_config() {
  TZ=$(jq -er '.timezone // "UTC"' "$CONFIG_PATH")
  SKIP_LIST=($(jq -r '.skip_list[]? // empty' "$CONFIG_PATH"))
  GOTIFY_URL=$(jq -r '.gotify_url // empty' "$CONFIG_PATH")
  APPRISE_URL=$(jq -r '.apprise_url // empty' "$CONFIG_PATH")
  MAILRISE_URL=$(jq -r '.mailrise_url // empty' "$CONFIG_PATH")
}

notify() {
  local message="$1"
  echo -e "$message" | tee -a "$LOG_FILE"
  [ -n "$GOTIFY_URL" ] && curl -s -X POST "$GOTIFY_URL" -F "title=Add-on Updater" -F "message=$message" >/dev/null
  [ -n "$APPRISE_URL" ] && curl -s -X POST "$APPRISE_URL" -d "$message" >/dev/null
  [ -n "$MAILRISE_URL" ] && curl -s -X POST "$MAILRISE_URL" -d "$message" >/dev/null
}

fetch_latest_tag() {
  local image="$1"
  local latest_tag=""

  # 1. Try Docker Hub
  local repo=$(echo "$image" | cut -d/ -f2)
  latest_tag=$(curl -fsSL "https://hub.docker.com/v2/repositories/${image}/tags?page_size=100" \
    | jq -er '.results[].name' \
    | grep -E '^[0-9]+\.[0-9]+' \
    | sort -V \
    | tail -1 || echo "")

  # 2. If empty and is lscr.io, try LinuxServer Fleet API
  if [[ -z "$latest_tag" && "$image" == lscr.io/* ]]; then
    local repo_name=$(echo "$image" | cut -d/ -f3)
    latest_tag=$(curl -fsSL "https://fleet.linuxserver.io/api/v1/images/$repo_name" \
      | jq -er '.image.tags[] | select(.name | test("^\\d+(\\.\\d+)*$")) | .name' \
      | sort -V \
      | tail -1 || echo "")
  fi

  echo "${latest_tag:-unknown}"
}

update_addon() {
  local addon_path="$1"
  local config="$addon_path/config.json"
  local name=$(safe_jq '.name' "$config")
  local image=$(safe_jq '.image_override // .image' "$config")
  local current_tag=$(safe_jq '.version' "$config")

  for skip in "${SKIP_LIST[@]}"; do
    [[ "$name" == "$skip" ]] && echo -e "${COLOR_CYAN}[SKIP] $name skipped${COLOR_RESET}" && return
  done

  local latest_tag
  latest_tag=$(fetch_latest_tag "$image")

  if [[ "$latest_tag" == "$current_tag" || "$latest_tag" == "unknown" ]]; then
    echo -e "${COLOR_GREEN}[OK] $name is up to date ($current_tag)${COLOR_RESET}"
    UNCHANGED_ADDONS["$name"]="$current_tag"
    return
  fi

  echo -e "${COLOR_YELLOW}[UPDATE] $name: $current_tag → $latest_tag${COLOR_RESET}"
  jq --arg v "$latest_tag" '.version = $v' "$config" > "$config.tmp" && mv "$config.tmp" "$config"
  UPDATED_ADDONS["$name"]="$latest_tag"

  if [[ -f "$addon_path/$CHANGELOG_FILE" ]]; then
    echo -e "## $latest_tag - $(date +'%Y-%m-%d')\n- Updated automatically to $latest_tag\n" | cat - "$addon_path/$CHANGELOG_FILE" > temp && mv temp "$addon_path/$CHANGELOG_FILE"
  else
    echo -e "## $latest_tag - $(date +'%Y-%m-%d')\n- Updated automatically to $latest_tag\n" > "$addon_path/$CHANGELOG_FILE"
  fi
}

commit_and_push() {
  cd "$REPO_DIR"
  git pull || notify "[GIT] ❌ Pull failed. Manual resolution may be required."

  if git diff --quiet && git diff --cached --quiet; then
    notify "[GIT] No changes to commit."
  else
    git add .
    git commit -m "🔄 Updated add-ons: ${!UPDATED_ADDONS[*]}"
    if git push; then
      notify "[GIT] ✅ Push succeeded."
    else
      notify "[GIT] ❌ Push failed."
    fi
  fi
}

main() {
  echo -e "${COLOR_BLUE}Starting Home Assistant Add-on Updater${COLOR_RESET}"
  read_config
  export TZ="$TZ"
  date

  if [ ! -d "$REPO_DIR/.git" ]; then
    git clone https://github.com/ChristoffBo/homeassistant "$REPO_DIR" || {
      notify "[GIT] ❌ Failed to clone repository."
      exit 1
    }
    notify "[GIT] ✅ Repository cloned successfully."
  else
    echo -e "${COLOR_BLUE}[GIT] Repo already cloned, continuing...${COLOR_RESET}"
  fi

  for addon_path in "$REPO_DIR"/*; do
    [[ -d "$addon_path" && -f "$addon_path/config.json" ]] || continue
    update_addon "$addon_path"
  done

  commit_and_push

  notify_summary="🧩 Add-on Updater Summary\n\n"
  if [ "${#UPDATED_ADDONS[@]}" -gt 0 ]; then
    notify_summary+="✅ Updated:\n"
    for name in "${!UPDATED_ADDONS[@]}"; do
      notify_summary+="• $name → ${UPDATED_ADDONS[$name]}\n"
    done
  fi

  if [ "${#UNCHANGED_ADDONS[@]}" -gt 0 ]; then
    notify_summary+="\n🆗 Unchanged:\n"
    for name in "${!UNCHANGED_ADDONS[@]}"; do
      notify_summary+="• $name (${UNCHANGED_ADDONS[$name]})\n"
    done
  fi

  notify "$notify_summary"
}

main