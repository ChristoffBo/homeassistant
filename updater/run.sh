#!/bin/bash
set -eo pipefail

# ======================
# CONFIGURATION
# ======================
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"

# ======================
# COLOR DEFINITIONS
# ======================
COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_DARK_BLUE="\033[0;94m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"
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
  export TZ
  DRY_RUN=$(jq -er '.dry_run // false' "$CONFIG_PATH")
  GITEA_TOKEN=$(jq -er '.gitea_token // empty' "$CONFIG_PATH")
  GITEA_REPO=$(jq -er '.gitea_repo // empty' "$CONFIG_PATH")
  GITHUB_TOKEN=$(jq -er '.github_token // empty' "$CONFIG_PATH")
  GITHUB_REPO=$(jq -er '.github_repo // empty' "$CONFIG_PATH")
  NOTIFY_URL=$(jq -er '.notify_url // empty' "$CONFIG_PATH")
  SKIP_LIST=( $(jq -r '.skip // [] | .[]' "$CONFIG_PATH") )
}

log() {
  local COLOR="$1"
  local MESSAGE="$2"
  echo -e "${COLOR}[$(date '+%Y-%m-%d %H:%M:%S %Z')] $MESSAGE${COLOR_RESET}" | tee -a "$LOG_FILE"
}

notify() {
  local MSG="$1"
  if [[ -n "$NOTIFY_URL" ]]; then
    curl -s -X POST -H "Content-Type: text/plain" -d "$MSG" "$NOTIFY_URL" || true
  fi
}

is_skipped() {
  local slug="$1"
  for item in "${SKIP_LIST[@]}"; do
    [[ "$item" == "$slug" ]] && return 0
  done
  return 1
}

get_latest_tag() {
  local image="$1"
  local latest_tag="unknown"

  # 1. Try Docker Hub
  latest_tag=$(curl -s "https://registry.hub.docker.com/v2/repositories/${image}/tags?page_size=1" |
    jq -er '.results[0].name' 2>/dev/null || echo "unknown")
  [[ "$latest_tag" != "unknown" ]] && echo "$latest_tag" && return

  # 2. Try lscr.io
  latest_tag=$(curl -s "https://fleet.linuxserver.io/api/v2/repositories/search?query=${image}" |
    jq -er '.data[0].versions[0].name' 2>/dev/null || echo "unknown")
  [[ "$latest_tag" != "unknown" ]] && echo "$latest_tag" && return

  # 3. Try GitHub container registry
  latest_tag=$(curl -s "https://ghcr.io/v2/${image}/tags/list" |
    jq -er '.tags[-1]' 2>/dev/null || echo "unknown")

  echo "$latest_tag"
}

update_addon() {
  local slug="$1"
  local config="$REPO_DIR/$slug/config.json"
  local current_tag=$(safe_jq '.version' "$config")
  local image=$(safe_jq '.image // empty' "$config")

  if [[ "$image" == "unknown" || -z "$image" ]]; then
    log "$COLOR_RED" "❌ $slug: No image found, skipping"
    return
  fi

  local latest_tag=$(get_latest_tag "$image")
  [[ "$latest_tag" == "unknown" ]] && log "$COLOR_YELLOW" "⚠️ $slug: Could not fetch latest tag" && return

  if [[ "$current_tag" != "$latest_tag" ]]; then
    log "$COLOR_GREEN" "⬆️ $slug updated from $current_tag to $latest_tag"
    UPDATED_ADDONS["$slug"]="$latest_tag"
    if [[ "$DRY_RUN" == "false" ]]; then
      jq --arg ver "$latest_tag" '.version = $ver' "$config" > "$config.tmp" && mv "$config.tmp" "$config"
    fi
  else
    log "$COLOR_BLUE" "✅ $slug is up to date ($current_tag)"
    UNCHANGED_ADDONS["$slug"]="$current_tag"
  fi
}

generate_changelog() {
  local DATE_TAG=$(date '+%Y-%m-%d')
  local changelog="$REPO_DIR/CHANGELOG.md"

  if [[ "$DRY_RUN" == "true" || "${#UPDATED_ADDONS[@]}" -eq 0 ]]; then return; fi
  touch "$changelog"

  {
    echo "## 🧩 Add-on Updates — $DATE_TAG"
    for slug in "${!UPDATED_ADDONS[@]}"; do
      echo "- **$slug** → \`${UPDATED_ADDONS[$slug]}\`"
    done
    echo ""
    cat "$changelog"
  } > "$changelog.tmp"

  mv "$changelog.tmp" "$changelog"
}

commit_and_push() {
  cd "$REPO_DIR"

  if ! git pull --rebase; then
    log "$COLOR_YELLOW" "⚠️ Pull failed due to unstaged changes — forcing reset"
    git fetch origin main && git reset --hard origin/main
    PULL_STATUS="⚠️ Git pull failed → fallback reset applied"
  else
    PULL_STATUS="✅ Git pull succeeded"
  fi

  if [[ "$DRY_RUN" == "true" || "${#UPDATED_ADDONS[@]}" -eq 0 ]]; then return; fi

  git config user.name "Updater"
  git config user.email "updater@homeassistant.local"
  git add .
  git commit -m "🔄 Updated add-ons: ${!UPDATED_ADDONS[*]}" || true

  if git push; then
    PUSH_STATUS="✅ Git push succeeded."
  else
    PUSH_STATUS="❌ Git push failed!"
  fi
}

main() {
  log "$COLOR_CYAN" "ℹ️ Starting Home Assistant Add-on Updater"
  read_config
  mkdir -p "$REPO_DIR"

  if [[ ! -d "$REPO_DIR/.git" ]]; then
    git clone "${GITEA_REPO:-$GITHUB_REPO}" "$REPO_DIR"
  else
    log "$COLOR_PURPLE" "[GIT] Repo already cloned, continuing..."
  fi

  cd "$REPO_DIR"
  git reset --hard

  for addon in "$REPO_DIR"/*/config.json; do
    slug=$(basename "$(dirname "$addon")")
    is_skipped "$slug" && log "$COLOR_YELLOW" "⏭️ Skipping $slug (listed)" && continue
    log "$COLOR_DARK_BLUE" "🔍 Checking $slug"
    update_addon "$slug"
  done

  generate_changelog
  commit_and_push

  SUMMARY="🧩 Add-on Update Summary:\n$PULL_STATUS\n$PUSH_STATUS"
  for slug in "${!UPDATED_ADDONS[@]}"; do
    SUMMARY+="\n✅ $slug → ${UPDATED_ADDONS[$slug]}"
  done
  for slug in "${!UNCHANGED_ADDONS[@]}"; do
    SUMMARY+="\n🟦 $slug unchanged (${UNCHANGED_ADDONS[$slug]})"
  done

  notify "$SUMMARY"
  log "$COLOR_GREEN" "ℹ️ Update process complete."
}

main