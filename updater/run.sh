#!/bin/bash
set -e

# =========[ ENV SETUP ]=========
TZ=$(jq -r '.TZ // "Europe/Brussels"' /data/options.json)
export TZ
CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
cd "$REPO_DIR" || exit 1

# =========[ COLOR CODES ]=========
RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m'
BLUE='\033[0;34m' CYAN='\033[0;36m' NC='\033[0m'

# =========[ LOGGING ]=========
log() {
  echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $*"
}
log_info() { echo -e "${GREEN}✔ $*${NC}"; }
log_warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
log_error() { echo -e "${RED}✖ $*${NC}" >&2; }
log_debug() { [[ "$DEBUG" == "true" ]] && echo -e "${CYAN}🐛 $*${NC}"; }

# =========[ NOTIFIERS ]=========
notify() {
  local message="$1"
  local url gotify_url mailrise_url apprise_url
  gotify_url=$(jq -r '.gotify_url // empty' "$CONFIG_PATH")
  mailrise_url=$(jq -r '.mailrise_url // empty' "$CONFIG_PATH")
  apprise_url=$(jq -r '.apprise_url // empty' "$CONFIG_PATH")

  if [[ -n "$gotify_url" ]]; then curl -s -X POST "$gotify_url" -F "title=Addon Updater" -F "message=$message" &>/dev/null; fi
  if [[ -n "$mailrise_url" ]]; then curl -s -X POST "$mailrise_url" -H "Title: Addon Updater" -d "$message" &>/dev/null; fi
  if [[ -n "$apprise_url" ]]; then curl -s -X POST "$apprise_url" -d "title=Addon Updater" -d "body=$message" &>/dev/null; fi
}

# =========[ TAG FILTER ]=========
filter_tags() {
  grep -v '^latest$' |
  grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}([-_a-zA-Z0-9]*)?$' |
  sort -Vr
}

strip_arch_prefix() {
  echo "$1" | sed -E 's/^(amd64|armv7|armhf|aarch64)[-_]?//'
}

# =========[ FETCH TAGS ]=========
get_dockerhub_tag() {
  local image="$1"
  local repo user tags resp
  user=$(echo "$image" | cut -d'/' -f1)
  repo=$(echo "$image" | cut -d'/' -f2)
  resp=$(curl -s "https://hub.docker.com/v2/repositories/${user}/${repo}/tags?page_size=100")
  tags=$(echo "$resp" | jq -r '.results[].name')

  log_debug "Tags from DockerHub for $image: $tags"
  printf "%s\n" $tags | filter_tags | head -n1
}

get_lsio_tag() {
  local image repo tags resp
  repo=$(basename "$image")
  resp=$(curl -s "https://hub.docker.com/v2/repositories/linuxserver/${repo}/tags?page_size=100")
  tags=$(echo "$resp" | jq -r '.results[].name')

  log_debug "Tags from LSIO for $image: $tags"
  printf "%s\n" $tags | filter_tags | head -n1
}

get_ghcr_tag() {
  local image org_repo tags resp
  org_repo=$(echo "$image" | cut -d'/' -f2-)
  resp=$(curl -s "https://ghcr.io/v2/$org_repo/tags/list")
  tags=$(echo "$resp" | jq -r '.tags[]')

  log_debug "Tags from GHCR for $image: $tags"
  printf "%s\n" $tags | filter_tags | head -n1
}

# =========[ VERSION CHECK ]=========
get_latest_version() {
  local image="$1"
  case "$image" in
    *linuxserver*) get_lsio_tag "$image" ;;
    ghcr.io/*) get_ghcr_tag "$image" ;;
    *) get_dockerhub_tag "$image" ;;
  esac
}

update_changelog() {
  local addon="$1"
  local new_ver="$2"
  local image="$3"
  local file="addons/$addon/CHANGELOG.md"

  {
    echo "## $(date '+%Y-%m-%d') - Updated to $new_ver"
    echo "- Docker image: \`$image:$new_ver\`"
    echo ""
    [[ -f "$file" ]] && cat "$file"
  } > "$file.tmp" && mv "$file.tmp" "$file"
}

update_addon() {
  local addon="$1"
  local image="$2"
  local current_ver="$3"
  local latest_ver stripped_current stripped_latest

  log "Checking ${addon}..."
  latest_ver=$(get_latest_version "$image")

  if [[ -z "$latest_ver" ]]; then
    log_warn "$addon: Could not determine latest tag"
    return
  fi

  stripped_current=$(strip_arch_prefix "$current_ver")
  stripped_latest=$(strip_arch_prefix "$latest_ver")

  if [[ "$stripped_current" == "$stripped_latest" ]]; then
    log_info "$addon is already up-to-date ($current_ver)"
    return
  fi

  log_info "$addon: New version available! $current_ver → $latest_ver"
  notify "$addon updated: $current_ver → $latest_ver"

  jq --arg ver "$latest_ver" '.image = $ver' "addons/$addon/config.json" > "addons/$addon/config.tmp"
  mv "addons/$addon/config.tmp" "addons/$addon/config.json"

  update_changelog "$addon" "$latest_ver" "$image"
  git add "addons/$addon"
  git commit -m "🔄 $addon: update to $latest_ver"
}

# =========[ START ]=========
log "🔁 Home Assistant Add-on Updater Starting"

git config --global user.name "Updater" && git config --global user.email "updater@local"
git pull --rebase || true

for dir in addons/*/; do
  [ -d "$dir" ] || continue
  config="$dir/config.json"
  [ -f "$config" ] || continue

  name=$(basename "$dir")
  image=$(jq -r '.image // empty' "$config")
  [[ -z "$image" ]] && continue

  current=$(jq -r '.version // empty' "$config")
  [[ -z "$current" ]] && continue

  update_addon "$name" "$image" "$current"
done

git push || true
log_info "✅ Add-on update check complete"
