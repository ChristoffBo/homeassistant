#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
REPO_DIR=/data/homeassistant
LOG_FILE="/data/updater.log"

GITHUB_TOKEN=$(jq -r '.github_token // empty' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username // empty' "$CONFIG_PATH")
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
CHECK_CRON=$(jq -r '.check_cron' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")

GIT_AUTH_REPO="$GITHUB_REPO"
if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
  GIT_AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
fi

log() {
  echo -e "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"
}

clone_repo() {
  if [ ! -d "$REPO_DIR" ]; then
    log "Cloning repo..."
    git clone "$GIT_AUTH_REPO" "$REPO_DIR"
  else
    cd "$REPO_DIR"
    git pull origin main
  fi
}

get_latest_linuxserver_tag() {
  local repo="${1#lscr.io/linuxserver/}"
  local tags_json
  tags_json=$(curl -s "https://api.linuxserver.io/dockerhub/tags?repo=$repo")
  echo "$tags_json" | jq -r '[.tags[] | select(.name != "latest")] | sort_by(.last_updated) | reverse | .[0].name'
}

get_latest_dockerhub_tag() {
  local image="$1"
  local repo="$image"
  [[ "$repo" != *"/"* ]] && repo="library/$repo"
  local tags_json
  tags_json=$(curl -s "https://registry.hub.docker.com/v2/repositories/$repo/tags?page_size=100")
  echo "$tags_json" | jq -r '[.results[] | select(.name != "latest")] | sort_by(.last_updated) | reverse | .[0].name'
}

get_latest_ghcr_tag() {
  local image="$1"
  # image like: ghcr.io/owner/repo[:tag]
  local repo_path
  repo_path=$(echo "$image" | sed -E 's|ghcr.io/([^:/]+/[^:/]+).*|\1|')

  if [ -z "$GITHUB_TOKEN" ]; then
    log "⚠️ GitHub token not set, cannot fetch GHCR tags for $repo_path"
    echo ""
    return
  fi

  local page=1
  local per_page=100
  local tags=()
  while : ; do
    local response
    response=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
      "https://api.github.com/repos/$repo_path/packages/container/$repo_path/versions?page=$page&per_page=$per_page")
    local names
    names=$(echo "$response" | jq -r '.[]?.metadata.container.tags[]?' 2>/dev/null | tr '\n' ' ')
    if [ -z "$names" ]; then
      break
    fi
    tags+=($names)
    ((page++))
  done

  # If no tags, fallback
  if [ "${#tags[@]}" -eq 0 ]; then
    echo ""
    return
  fi

  # Sort tags descending (assuming semantic or date order)
  printf '%s\n' "${tags[@]}" | sort -r | head -n 1
}

clean_image_field() {
  local img_field="$1"
  if [[ "$img_field" =~ ^\{.*\}$ ]]; then
    echo "$img_field" | jq -c .
  else
    echo "$img_field"
  fi
}

update_addon() {
  local path="$1"
  local config="$path/config.json"
  local updater="$path/updater.json"

  local slug=$(jq -r '.slug' "$config")
  local current_version=$(jq -r '.version' "$config" | sed -r 's/\x1B\[[0-9;]*[mK]//g' | tr -d '[:space:]')

  local image=$(jq -r '.image // empty' "$config")
  if [[ -z "$image" || "$image" == "null" ]]; then
    log "⚠️ $slug missing image field, skipping"
    return
  fi

  local latest=""
  if [[ "$image" == lscr.io/linuxserver/* ]]; then
    latest=$(get_latest_linuxserver_tag "$image")
  elif [[ "$image" == ghcr.io/* ]]; then
    latest=$(get_latest_ghcr_tag "$image")
  else
    local base_image="${image%%:*}"
    latest=$(get_latest_dockerhub_tag "$base_image")
  fi

  if [[ -z "$latest" ]]; then
    log "⚠️ Could not find latest tag for $slug, skipping"
    return
  fi

  log "Addon: $slug"
  log "Current version: $current_version"
  log "Latest version: $latest"

  if [[ "$latest" != "$current_version" ]]; then
    jq --arg v "$latest" '.version = $v' "$config" > "$config.tmp" && mv "$config.tmp" "$config"

    local clean_img=$(clean_image_field "$image")

    local timestamp=$(TZ="$TIMEZONE" date '+%d-%m-%Y %H:%M')
    if [ -f "$updater" ]; then
      jq --arg v "$latest" --arg dt "$timestamp" --arg img "$clean_img" \
        '.upstream_version=$v | .last_update=$dt | .image=$img' "$updater" > "$updater.tmp" && mv "$updater.tmp" "$updater"
    else
      jq -n --arg slug "$slug" --arg v "$latest" --arg dt "$timestamp" --arg img "$clean_img" \
        '{slug: $slug, upstream_version: $v, last_update: $dt, image: $img}' > "$updater"
    fi

    log "✅ Updated $slug to version $latest"
  else
    log "✔️ $slug is already up to date"
  fi
}

main() {
  clone_repo
  cd "$REPO_DIR" || exit

  for d in */ ; do
    if [ -f "$d/config.json" ]; then
      update_addon "$d"
    fi
  done

  if git status --porcelain | grep .; then
    git add .
    git commit -m "⬆️ Update addon versions"
    git push origin main
    log "✅ Changes pushed to repo."
  else
    log "No changes to commit."
  fi
}

main
