update_addon_if_needed() {
  local addon_path="$1"
  local updater_file="$addon_path/updater.json"
  local config_file="$addon_path/config.json"
  local changelog_file="$addon_path/CHANGELOG.md"
  local slug
  slug=$(basename "$addon_path")

  # Check if config.json exists and version is non-empty (indicates docker image addon)
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

  # ...rest of update_addon_if_needed continues as before
