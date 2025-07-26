update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local changelog_file="$addon_path/CHANGELOG.md"
  local slug
  slug=$(basename "$addon_path")

  if [ ! -f "$config_file" ]; then
    echo "No config.json found in $addon_path, skipping updater.json creation."
    return
  fi

  local config_version
  config_version=$(jq -r '.version // empty' "$config_file")

  if [ -z "$config_version" ]; then
    echo "Addon '$slug' has empty version in config.json, assuming no docker image, skipping updater.json creation."
    return
  fi

  if [ ! -f "$updater_file" ]; then
    echo "No updater.json found in $addon_path, creating one with defaults..."
    cat > "$updater_file" << EOF
{
  "slug": "$slug",
  "upstream_repo": "",
  "upstream_version": "",
  "last_update": "Never"
}
EOF
  fi

  local upstream_repo
  upstream_repo=$(jq -r '.upstream_repo' "$updater_file")
  local current_version
  current_version=$(jq -r '.upstream_version' "$updater_file")
  local last_update
  last_update=$(jq -r '.last_update // "Never"' "$updater_file")

  if [ -z "$upstream_repo" ]; then
    echo "No 'upstream_repo' set in updater.json for $slug, skipping update check."
    echo "----------------------------"
    return
  fi

  local latest_version
  latest_version=$(get_latest_docker_tag "$upstream_repo")

  if [ -z "$latest_version" ]; then
    echo "Could not fetch latest docker tag for repo $upstream_repo"
    echo "Skipping update check for $slug due to missing latest tag."
    echo "----------------------------"
    return
  fi

  local now_datetime
  now_datetime=$(date '+%d-%m-%Y %H:%M')

  echo "----------------------------"
  echo "Addon: $slug"
  echo -e "${YELLOW}Last updated: $last_update${NC}"

  # Update if needed
  if [ "$latest_version" != "$current_version" ]; then
    jq --arg v "$latest_version" --arg dt "$now_datetime" \
      '.upstream_version = $v | .last_update = $dt' "$updater_file" > "$updater_file.tmp" && mv "$updater_file.tmp" "$updater_file"

    if [ -f "$config_file" ]; then
      jq --arg v "$latest_version" '.version = $v' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
      echo -e "${GREEN}Updated config.json version to $latest_version${NC}"
    else
      echo "No config.json found in $addon_path"
    fi

    if [ ! -f "$changelog_file" ]; then
      touch "$changelog_file"
      echo "Created new CHANGELOG.md"
    fi

    {
      echo "v$latest_version ($now_datetime)"
      echo ""
      echo "    Update to latest version from $upstream_repo (changelog : https://github.com/${upstream_repo#*/}/releases)"
      echo ""
    } >> "$changelog_file"

    echo -e "${GREEN}Addon '$slug' updated to $latest_version ⬆️${NC}"
  fi

  # Refresh current version after potential update
  config_version=$(jq -r '.version // empty' "$config_file")

  echo "Current Docker version: $config_version"
  echo "Latest Docker version:  $latest_version"

  if [ "$config_version" = "$latest_version" ]; then
    echo -e "${BLUE}Addon '$slug' is already up-to-date ✔${NC}"
  fi
  echo "----------------------------"
}
