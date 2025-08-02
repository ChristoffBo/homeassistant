#!/bin/sh
set -e

# Fix critical $HOME not set error
export HOME=/config

# Show repository source
echo "===== ADDON UPDATER STARTED ====="
echo "[Source] Repository: https://github.com/$REPO_PATH.git"

# Load configuration
CONFIG_FILE="/data/options.json"
GIT_USER=$(jq -r '.gituser' "$CONFIG_FILE")
GIT_EMAIL=$(jq -r '.gitmail' "$CONFIG_FILE")
REPO_PATH=$(jq -r '.repository' "$CONFIG_FILE")
VERBOSE=$(jq -r '.verbose' "$CONFIG_FILE")
DRY_RUN=$(jq -r '.dry_run' "$CONFIG_FILE")
ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications' "$CONFIG_FILE")
GOTIFY_URL=$(jq -r '.gotify_url' "$CONFIG_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token' "$CONFIG_FILE")

# Supervisor token from environment (automatically injected by Home Assistant)
SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

# Set log level
if [ "$VERBOSE" = "true" ]; then
  LOG_LEVEL="DEBUG"
else
  LOG_LEVEL="INFO"
fi

# Handle logging configuration - moved to persistent storage
LOG_FILE="/data/.addons_updater_logging"  # Changed to persistent location
if [ ! -f "$LOG_FILE" ]; then
  echo "Creating logging configuration in persistent storage..."
  echo "level=$LOG_LEVEL" > "$LOG_FILE"
else
  sed -i "s/level=.*/level=$LOG_LEVEL/g" "$LOG_FILE"
fi

# Configure Git with safe directory
git config --global user.name "$GIT_USER"
git config --global user.email "$GIT_EMAIL"
git config --global pull.rebase false
git config --global --add safe.directory /data/repo  # Critical for container security

# Determine repository URL
REPO_URL="https://github.com/$REPO_PATH.git"
echo "Using repository URL: $REPO_URL"

# Set up repository
REPO_DIR="/data/repo"
if [ -d "$REPO_DIR/.git" ]; then
  echo "Updating existing repository..."
  cd "$REPO_DIR"
  git reset --hard HEAD  # Clean working directory
  git pull
  echo "Successfully pulled latest changes from $REPO_URL"
else
  echo "Cloning repository..."
  git clone "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
  echo "Successfully cloned repository from $REPO_URL"
fi

# Main processing function
process_addons() {
  ADDONS_DIR="$REPO_DIR/addons"
  if [ ! -d "$ADDONS_DIR" ]; then
    echo "ERROR: Addons directory not found: $ADDONS_DIR" >&2
    return
  fi

  echo "Starting addon processing..."
  UPDATED_COUNT=0
  CHECKED_COUNT=0
  PROCESSED=""
  UPDATED=""

  for addon in "$ADDONS_DIR"/*; do
    [ -d "$addon" ] || continue
    addon_name=$(basename "$addon")
    CHECKED_COUNT=$((CHECKED_COUNT + 1))
    echo "Processing $addon_name..."
    
    # Get current version
    config_file="$addon/config.json"
    if [ ! -f "$config_file" ]; then
      echo "WARNING: Missing config.json for $addon_name" >&2
      PROCESSED="$PROCESSED\n$addon_name|missing_config|||"
      continue
    fi

    current_version=$(jq -r '.version' "$config_file")
    image_name=$(jq -r '.image' "$config_file" | awk -F'/' '{print $NF}')
    if [ -z "$image_name" ]; then
      echo "WARNING: Missing image name for $addon_name" >&2
      PROCESSED="$PROCESSED\n$addon_name|missing_image|||"
      continue
    fi

    echo "Checking registries for $image_name (current: $current_version)..."

    # Check registries for latest version
    latest_version=""
    # Docker Hub
    echo "Checking Docker Hub..."
    dockerhub_version=$(curl --max-time 30 -s "https://registry.hub.docker.com/v2/repositories/$image_name/tags?page_size=100" | 
                        jq -r '.results[].name' | 
                        grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | 
                        sort -V | tail -n1)
    
    # GHCR
    echo "Checking GHCR..."
    ghcr_version=$(curl --max-time 30 -s -H "Authorization: Bearer $(curl -s "https://ghcr.io/token?service=ghcr.io&scope=repository:$image_name:pull" | jq -r '.token')" \
                  "https://ghcr.io/v2/$image_name/tags/list" | 
                  jq -r '.tags[]' | 
                  grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | 
                  sort -V | tail -n1)
    
    # Linuxserver.io
    echo "Checking LinuxServer.io..."
    lsi_version=$(curl --max-time 30 -s "https://registry.hub.docker.com/v2/repositories/linuxserver/$image_name/tags?page_size=100" | 
                 jq -r '.results[].name' | 
                 grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | 
                 sort -V | tail -n1)

    # Find the latest version
    latest_version=$(printf "%s\n%s\n%s" "$dockerhub_version" "$ghcr_version" "$lsi_version" | 
                    grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | 
                    sort -V | tail -n1)

    if [ -z "$latest_version" ]; then
      echo "WARNING: No valid version found for $image_name" >&2
      PROCESSED="$PROCESSED\n$addon_name|no_registry_version|$current_version||"
      continue
    fi

    # Compare versions
    if [ "$current_version" = "$latest_version" ]; then
      echo "$addon_name is up to date ($current_version)"
      PROCESSED="$PROCESSED\n$addon_name|up_to_date|$current_version||"
      continue
    fi

    echo "Update available for $addon_name: $current_version -> $latest_version"

    # Update files
    updated_files=0
    
    # Update config.json
    if jq --arg version "$latest_version" '.version = $version' "$config_file" > tmp.json && mv tmp.json "$config_file"; then
      updated_files=$((updated_files+1))
    fi
    
    # Update build.json if exists
    build_file="$addon/build.json"
    if [ -f "$build_file" ]; then
      if jq --arg version "$latest_version" '.version = $version' "$build_file" > tmp.json && mv tmp.json "$build_file"; then
        updated_files=$((updated_files+1))
      fi
    fi
    
    # Update update.json if exists
    update_file="$addon/update.json"
    if [ -f "$update_file" ]; then
      if jq --arg version "$latest_version" '.version = $version' "$update_file" > tmp.json && mv tmp.json "$update_file"; then
        updated_files=$((updated_files+1))
      fi
    fi

    if [ "$updated_files" -eq 0 ]; then
      echo "ERROR: Failed to update files for $addon_name" >&2
      PROCESSED="$PROCESSED\n$addon_name|update_failed|$current_version|$latest_version|"
      continue
    fi

    # Create or update CHANGELOG.md
    changelog_file="$addon/CHANGELOG.md"
    today=$(date +%Y-%m-%d)
    if [ ! -f "$changelog_file" ]; then
      echo "# $addon_name Changelog" > "$changelog_file"
    fi
    {
      echo "## $latest_version - $today"
      echo "- Updated from $current_version to $latest_version"
      echo "- [Docker Image](https://hub.docker.com/r/$image_name)"
      echo ""
    } >> "$changelog_file"

    # Add changes to Git
    git add "$config_file"
    [ -f "$build_file" ] && git add "$build_file"
    [ -f "$update_file" ] && git add "$update_file"
    git add "$changelog_file"
    
    # Commit changes
    git commit -m "Update $addon_name to $latest_version"
    
    UPDATED="$UPDATED\n$addon_name|$current_version|$latest_version"
    UPDATED_COUNT=$((UPDATED_COUNT + 1))
    PROCESSED="$PROCESSED\n$addon_name|updated|$current_version|$latest_version|"
    echo "Successfully updated $addon_name"
  done

  # Return results
  printf "PROCESSED=%s\nUPDATED=%s\nUPDATED_COUNT=%d\nCHECKED_COUNT=%d" "$PROCESSED" "$UPDATED" "$UPDATED_COUNT" "$CHECKED_COUNT"
}

# Run the processing
echo "Starting addon update process..."
results=$(process_addons)
eval "$results"

echo "Processed $CHECKED_COUNT addons, updated $UPDATED_COUNT"

# Push changes if updates were made
if [ "$UPDATED_COUNT" -gt 0 ] && [ "$DRY_RUN" = "false" ]; then
  echo "Pushing changes to repository..."
  git push origin main
  echo "[Destination] Successfully pushed updates to: $REPO_URL"
  
  # Trigger Home Assistant reload
  if [ -n "$SUPERVISOR_TOKEN" ]; then
    echo "Triggering Home Assistant reload..."
    curl -s -o /dev/null \
      -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
      -H "Content-Type: application/json" \
      -X POST \
      http://supervisor/store/reload
    echo "Store reload triggered successfully"
  else
    echo "WARNING: Supervisor token not available, skipping reload"
  fi
fi

# Send Gotify notification
if [ "$ENABLE_NOTIFICATIONS" = "true" ] && [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
  echo "Sending Gotify notification..."
  
  # Prepare message
  message="### Addon Update Report\n\n"
  message+="#### 🔍 Checked Addons ($CHECKED_COUNT):\n"
  
  # Parse processed addons
  printf "%s" "$PROCESSED" | tail -n +2 | while IFS='|' read -r name status current latest _; do
    case $status in
      updated)
        message+="- ✅ **$name**: Updated to $latest\n"
        ;;
      up_to_date)
        message+="- ✔️ **$name**: Up-to-date ($current)\n"
        ;;
      no_registry_version)
        message+="- ⚠️ **$name**: No registry version found\n"
        ;;
      missing_config)
        message+="- ❌ **$name**: Missing config.json\n"
        ;;
      missing_image)
        message+="- ❌ **$name**: Missing image name\n"
        ;;
      update_failed)
        message+="- ❌ **$name**: Update failed\n"
        ;;
      *)
        message+="- ❓ **$name**: $status\n"
        ;;
    esac
  done

  # Add updated section if any
  if [ "$UPDATED_COUNT" -gt 0 ]; then
    message+="\n#### 🔄 Updated Addons ($UPDATED_COUNT):\n"
    printf "%s" "$UPDATED" | tail -n +2 | while IFS='|' read -r name old new; do
      message+="- ➡️ **$name**: $old → $new\n"
    done
  else
    message+="\n#### 🔄 Updated Addons: No updates\n"
  fi

  # Add summary
  message+="\n📊 **Summary**: $UPDATED_COUNT updated, $CHECKED_COUNT checked"
  
  # Send notification
  curl -s -o /dev/null -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"title\": \"Home Assistant Addon Updates\",
      \"message\": \"$message\",
      \"priority\": 5,
      \"extras\": {
        \"client::display\": {
          \"contentType\": \"text/markdown\"
        }
      }
    }"
fi

echo "Addon update process completed successfully"
echo "===== ADDON UPDATER FINISHED ====="
exit 0
