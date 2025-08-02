#!/bin/sh
set -e

CONFIG_PATH="/data/options.json"
REPO_DIR="/data/homeassistant"
LOG_FILE="/data/updater.log"

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[0;32m"
COLOR_BLUE="\033[0;34m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_PURPLE="\033[0;35m"

# Global state
UPDATED_ADDONS=""
UNCHANGED_ADDONS=""
SKIP_ADDONS="heimdall updater"

log() {
  printf "%s %b%s\n" "$(date '+[%Y-%m-%d %H:%M:%S %Z]')" "$1" "$COLOR_RESET" | tee -a "$LOG_FILE"
}

safe_jq() {
  expr="$1"
  file="$2"
  val=$(jq -e -r "$expr" "$file" 2>/dev/null)
  echo "$val" | grep -E '^[[:alnum:]\.\-_]+$' || echo "unknown"
}

read_config() {
  REPO=$(jq -r '.repository // empty' "$CONFIG_PATH")
  USER=$(jq -r '.gituser // empty' "$CONFIG_PATH")
  TOKEN=$(jq -r '.gittoken // empty' "$CONFIG_PATH")
  TZ=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")
  export TZ

  DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_PATH")
  DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")
  SKIP_PUSH=$(jq -r '.skip_push // false' "$CONFIG_PATH")

  NOTIFY_ENABLED=$(jq -r '.enable_notifications // false' "$CONFIG_PATH")
  NOTIFY_SERVICE=$(jq -r '.notification_service // ""' "$CONFIG_PATH")
  NOTIFY_URL=$(jq -r '.notification_url // ""' "$CONFIG_PATH")
  NOTIFY_TOKEN=$(jq -r '.notification_token // ""' "$CONFIG_PATH")
  NOTIFY_TO=$(jq -r '.notification_to // ""' "$CONFIG_PATH")
  NOTIFY_SUCCESS=$(jq -r '.notify_on_success // false' "$CONFIG_PATH")
  NOTIFY_ERROR=$(jq -r '.notify_on_error // true' "$CONFIG_PATH")
  NOTIFY_UPDATES=$(jq -r '.notify_on_updates // true' "$CONFIG_PATH")

  if [ -n "$USER" ] && [ -n "$TOKEN" ]; then
    GIT_REPO=$(echo "$REPO" | sed "s|https://|https://$USER:$TOKEN@|")
  else
    GIT_REPO="$REPO"
  fi
}

notify() {
  title="$1"
  message="$2"
  priority="$3"

  [ "$NOTIFY_ENABLED" != "true" ] && return

  case "$priority" in
    0) [ "$NOTIFY_SUCCESS" != "true" ] && return ;;
    3) [ "$NOTIFY_UPDATES" != "true" ] && return ;;
    5) [ "$NOTIFY_ERROR" != "true" ] && return ;;
  esac

  if [ "$NOTIFY_SERVICE" = "gotify" ]; then
    payload=$(jq -n --arg t "$title" --arg m "$message" --argjson p "$priority" \
      '{title: $t, message: $m, priority: $p}')

    resp=$(curl -s -w "%{http_code}" -o /tmp/ntf.out \
      -X POST "${NOTIFY_URL%/}/message?token=${NOTIFY_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$payload")

    if [ "$resp" != "200" ]; then
      log "$COLOR_RED❌ Gotify notification failed (HTTP $resp): $(cat /tmp/ntf.out)"
    fi
  fi
}

get_latest_tag() {
  image="$1"
  [ -z "$image" ] && return

  arch=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
  image=$(echo "$image" | sed "s/{arch}/$arch/")
  image_name="${image%%:*}"
  cache="/tmp/tags_$(echo "$image_name" | tr '/' '_').txt"

  if [ -f "$cache" ] && [ $(($(date +%s) - $(stat -c %Y "$cache"))) -lt 14400 ]; then
    cat "$cache"
    return
  fi

  if echo "$image_name" | grep -q "^ghcr.io/"; then
    path="${image_name#ghcr.io/}"
    token=$(curl -sf "https://ghcr.io/token?scope=repository:$path:pull" | jq -r '.token')
    tags=$(curl -sf -H "Authorization: Bearer $token" "https://ghcr.io/v2/$path/tags/list" | jq -r '.tags[]?')

  elif echo "$image_name" | grep -qE "^(linuxserver|lscr.io)/"; then
    name="${image_name##*/}"
    tags=$(curl -sf "https://fleet.linuxserver.io/api/v1/images/$name/tags" | jq -r '.tags[].name')

  else
    ns_repo="${image_name/library\//}"
    tags=""
    page=1
    while true; do
      result=$(curl -sf "https://hub.docker.com/v2/repositories/${ns_repo}/tags?page=$page&page_size=100") || break
      page_tags=$(echo "$result" | jq -r '.results[].name')
      [ -z "$page_tags" ] && break
      tags="$tags\n$page_tags"
      [ "$(echo "$result" | jq -r '.next')" = "null" ] && break
      page=$((page + 1))
    done
  fi

  echo "$tags" | grep -E '^[vV]?[0-9]+(\.[0-9]+){1,2}(-[a-z0-9]+)?$' | grep -viE 'latest|dev|rc|beta' | sort -Vr | head -n1 | tee "$cache"
}

update_addon() {
  addon="$1"
  name=$(basename "$addon")

  echo "$SKIP_ADDONS" | grep -qw "$name" && return

  config="$addon/config.json"
  build="$addon/build.json"
  image=$(jq -r '.image // empty' "$config" 2>/dev/null)
  version=$(safe_jq '.version' "$config")

  if [ -z "$image" ] && [ -f "$build" ]; then
    image=$(jq -r '.build_from.amd64 // .build_from' "$build" | jq -r 'strings')
    version=$(safe_jq '.version' "$build")
  fi

  if [ -z "$image" ]; then
    log "$COLOR_YELLOW⚠️  No image found for $name"
    UNCHANGED_ADDONS="$UNCHANGED_ADDONS\n$name: ⚠️ No image"
    return
  fi

  latest=$(get_latest_tag "$image")
  if [ -z "$latest" ]; then
    log "$COLOR_YELLOW⚠️  No valid version tag found for $image"
    UNCHANGED_ADDONS="$UNCHANGED_ADDONS\n$name: ❓ No tag"
    return
  fi

  if [ "$version" != "$latest" ]; then
    log "$COLOR_GREEN⬆️  $name updated from $version to $latest"
    UPDATED_ADDONS="$UPDATED_ADDONS\n$name: 🔄 $version → $latest"

    [ "$DRY_RUN" = "true" ] && {
      log "$COLOR_PURPLE💡 Dry run: skipping update of $name"
      return
    }

    jq --arg v "$latest" '.version = $v' "$config" > "$config.tmp" && mv "$config.tmp" "$config"
    [ -f "$build" ] && jq --arg v "$latest" '.version = $v' "$build" > "$build.tmp" && mv "$build.tmp" "$build"

    changelog="$addon/CHANGELOG.md"
    touch "$changelog"
    link="https://hub.docker.com/r/${image%%:*}/tags"
    echo "$image" | grep -q "^ghcr.io/" && link="https://github.com/${image#ghcr.io/}/pkgs/container/${image##*/}/tags"

    printf "## %s\n- Updated from %s to %s\n- Docker: [%s](%s)\n\n" "$latest" "$version" "$latest" "$image" "$link" | cat - "$changelog" > "$changelog.tmp"
    mv "$changelog.tmp" "$changelog"
  else
    log "$COLOR_BLUE✅ $name is up to date ($version)"
    UNCHANGED_ADDONS="$UNCHANGED_ADDONS\n$name: ✅ $version"
  fi
}

commit_and_push() {
  cd "$REPO_DIR"
  git config user.email "addon@local"
  git config user.name "Addon Updater"
  if [ -n "$(git status --porcelain)" ]; then
    git add . && git commit -m "🔄 Updated versions"
    [ "$SKIP_PUSH" = "true" ] || git push "$GIT_REPO" main || log "$COLOR_RED❌ Git push failed"
  else
    log "$COLOR_PURPLEℹ️  No changes to commit"
  fi
}

main() {
  echo "" > "$LOG_FILE"
  read_config
  log "$COLOR_BLUEℹ️ Starting Home Assistant Add-on Updater"

  rm -rf "$REPO_DIR"
  git clone --depth 1 "$GIT_REPO" "$REPO_DIR" || {
    log "$COLOR_RED❌ Git clone failed"
    notify "Updater Error" "Git clone failed" 5
    exit 1
  }

  for dir in "$REPO_DIR"/*; do
    [ -d "$dir" ] && update_addon "$dir"
  done

  commit_and_push

  summary="📦 Add-on Update Summary\n🕒 $(date '+%Y-%m-%d %H:%M:%S %Z')\n"
  [ -n "$UPDATED_ADDONS" ] && summary="$summary\n$UPDATED_ADDONS"
  [ -n "$UNCHANGED_ADDONS" ] && summary="$summary\n$UNCHANGED_ADDONS"
  [ "$DRY_RUN" = "true" ] && summary="$summary\n\n🔁 DRY RUN ENABLED"

  notify "Add-on Updater" "$summary" 3
  log "$COLOR_GREEN✅ Update process complete"
}

main