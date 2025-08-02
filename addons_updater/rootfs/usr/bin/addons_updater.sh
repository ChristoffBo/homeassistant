#!/bin/sh
set -e

# Start time for performance tracking
START_TIME=$(date +%s)

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Fix critical $HOME not set error
export HOME=/config

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
TIMEOUT=$(jq -r '.timeout // 30' "$CONFIG_FILE")  # Default 30 seconds per request

# ================== FIXED URL HANDLING ==================
# Normalize repository URL
REPO_URL=""
case "$REPO_PATH" in
  http*)
    # Handle full URLs
    CLEAN_PATH=$(echo "$REPO_PATH" | sed 's/\.git$//; s/\/$//')
    REPO_URL="$CLEAN_PATH.git"
    ;;
  *)
    # Handle shorthand notation
    CLEAN_PATH=$(echo "$REPO_PATH" | sed 's/\.git$//; s/\/$//')
    REPO_URL="https://github.com/$CLEAN_PATH.git"
    ;;
esac

# Show repository source
echo -e "${CYAN}"
echo "===== ADDON UPDATER STARTED ====="
echo -e "${NC}"
echo -e "${BLUE}[Source]${NC} Repository: $REPO_URL"
echo -e "${BLUE}[Mode]${NC} Dry Run: $DRY_RUN"
echo -e "${BLUE}[Timeout]${NC} $TIMEOUT seconds per registry"

# Supervisor token from environment
SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

# Configure Git
git config --global user.name "$GIT_USER"
git config --global user.email "$GIT_EMAIL"
git config --global pull.rebase false
git config --global --add safe.directory /data/repo

# Set up repository with shallow clone for speed
REPO_DIR="/data/repo"
if [ -d "$REPO_DIR/.git" ]; then
  echo -e "${BLUE}[Git]${NC} Updating existing repository..."
  cd "$REPO_DIR"
  git fetch --depth 1
  
  # Detect default branch
  DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $3}')
  if [ -z "$DEFAULT_BRANCH" ]; then
    echo -e "${YELLOW}⚠ Failed to detect default branch, using 'main' as fallback${NC}"
    DEFAULT_BRANCH="main"
  fi
  echo -e "${BLUE}[Git]${NC} Using detected branch: ${CYAN}$DEFAULT_BRANCH${NC}"
  
  git reset --hard origin/$DEFAULT_BRANCH
  echo -e "${GREEN}✓ Repository updated${NC}"
else
  echo -e "${BLUE}[Git]${NC} Shallow cloning repository..."
  git clone --depth 1 "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
  
  # Detect default branch
  DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $3}')
  if [ -z "$DEFAULT_BRANCH" ]; then
    echo -e "${YELLOW}⚠ Failed to detect default branch, using 'main' as fallback${NC}"
    DEFAULT_BRANCH="main"
  fi
  echo -e "${BLUE}[Git]${NC} Using detected branch: ${CYAN}$DEFAULT_BRANCH${NC}"
  
  echo -e "${GREEN}✓ Repository cloned${NC}"
fi

# ================== ADDONS DIRECTORY DETECTION ==================
# Check if addons are in a subdirectory named 'homeassistant'
if [ -d "$REPO_DIR/homeassistant" ]; then
  ADDONS_DIR="$REPO_DIR/homeassistant"
  echo -e "${BLUE}[Structure]${NC} Using addons in ${CYAN}homeassistant/${NC} subdirectory"
else
  ADDONS_DIR="$REPO_DIR"
  echo -e "${BLUE}[Structure]${NC} Using addons in repository root"
fi

# List all addon directories
echo -e "${BLUE}[Structure]${NC} Addons directory: ${CYAN}$ADDONS_DIR${NC}"

# Function to get Docker image version
get_docker_version() {
  local image=$1
  local url=$2
  local auth_header=$3
  local timeout=$4
  
  # Try to get version with timeout
  response=$(curl -s -m $timeout -H "$auth_header" "$url" 2>/dev/null)
  
  # Return if empty response
  if [ -z "$response" ]; then
    return
  fi
  
  # Extract version numbers
  echo "$response" | jq -r '.tags[]' 2>/dev/null | \
  grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | \
  sort -V | tail -n1
}

# Normalize version string by removing 'v' prefix
normalize_version() {
  echo "$1" | sed 's/^v//'
}

# Compare two version numbers
compare_versions() {
  local ver1=$(normalize_version "$1")
  local ver2=$(normalize_version "$2")
  
  if [ "$ver1" = "$ver2" ]; then
    echo 0
  elif [ "$(printf "%s\n%s" "$ver1" "$ver2" | sort -V | head -n1)" = "$ver1" ]; then
    echo -1  # ver1 < ver2
  else
    echo 1   # ver1 > ver2
  fi
}

# Main processing function
process_addons() {
  echo -e "${CYAN}"
  echo "===== CHECKING ADDONS ====="
  echo -e "${NC}"
  
  UPDATED_COUNT=0
  CHECKED_COUNT=0
  PROCESSED=""
  UPDATED=""

  # List of directories to skip
  SKIP_DIRS=".git addons_updater .github .DS_Store __MACOSX"

  # Loop through each directory in the addons directory
  for addon in "$ADDONS_DIR"/*; do
    # Skip if not a directory
    [ -d "$addon" ] || continue
    
    addon_name=$(basename "$addon")
    
    # Skip excluded directories
    case " $SKIP_DIRS " in
      *" $addon_name "*)
        [ "$VERBOSE" = "true" ] && echo -e "${BLUE}[Addon]${NC} ${CYAN}$addon_name${NC} ${YELLOW}(skipped)${NC}"
        continue
        ;;
    esac

    CHECKED_COUNT=$((CHECKED_COUNT + 1))
    [ "$VERBOSE" = "true" ] && echo -e "${BLUE}[Addon]${NC} ${CYAN}$addon_name${NC}"
    
    # Get current version
    config_file="$addon/config.json"
    if [ ! -f "$config_file" ]; then
      [ "$VERBOSE" = "true" ] && echo -e "  ${YELLOW}⚠ Missing config.json${NC}"
      PROCESSED="${PROCESSED}${addon_name}|missing_config|||"
      continue
    fi

    # Safely parse JSON
    current_version=$(jq -r '.version' "$config_file" 2>/dev/null || echo "")
    image_name=$(jq -r '.image' "$config_file" 2>/dev/null | awk -F'/' '{print $NF}' 2>/dev/null || echo "")
    
    # Handle empty image names
    if [ -z "$image_name" ] || [ "$image_name" = "null" ]; then
      [ "$VERBOSE" = "true" ] && echo -e "  ${YELLOW}⚠ Missing image name${NC}"
      PROCESSED="${PROCESSED}${addon_name}|missing_image|||"
      continue
    fi

    [ "$VERBOSE" = "true" ] && echo -e "  - Current: ${YELLOW}$current_version${NC}"
    [ "$VERBOSE" = "true" ] && echo -e "  - Image: ${CYAN}$image_name${NC}"

    # Check registries for latest version
    latest_version=""
    
    # Docker Hub
    dockerhub_url="https://registry.hub.docker.com/v2/repositories/$image_name/tags?page_size=100"
    dockerhub_version=$(get_docker_version "$image_name" "$dockerhub_url" "" "$TIMEOUT")
    [ -n "$dockerhub_version" ] && [ "$VERBOSE" = "true" ] && echo -e "    - Docker Hub: ${GREEN}$dockerhub_version${NC}"
    
    # GHCR
    ghcr_token=$(curl -s -m $TIMEOUT "https://ghcr.io/token?service=ghcr.io&scope=repository:$image_name:pull" | jq -r '.token' 2>/dev/null || echo "")
    if [ -n "$ghcr_token" ]; then
      ghcr_url="https://ghcr.io/v2/$image_name/tags/list"
      ghcr_version=$(get_docker_version "$image_name" "$ghcr_url" "Authorization: Bearer $ghcr_token" "$TIMEOUT")
      [ -n "$ghcr_version" ] && [ "$VERBOSE" = "true" ] && echo -e "    - GHCR: ${GREEN}$ghcr_version${NC}"
    fi
    
    # Linuxserver.io
    lsi_url="https://registry.hub.docker.com/v2/repositories/linuxserver/$image_name/tags?page_size=100"
    lsi_version=$(get_docker_version "$image_name" "$lsi_url" "" "$TIMEOUT")
    [ -n "$lsi_version" ] && [ "$VERBOSE" = "true" ] && echo -e "    - LinuxServer.io: ${GREEN}$lsi_version${NC}"

    # Find the latest version
    latest_version=$(printf "%s\n%s\n%s" "$dockerhub_version" "$ghcr_version" "$lsi_version" | 
                    grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | 
                    sort -V | tail -n1)

    if [ -z "$latest_version" ]; then
      [ "$VERBOSE" = "true" ] && echo -e "  ${YELLOW}⚠ No valid version found${NC}"
      PROCESSED="${PROCESSED}${addon_name}|no_registry_version|$current_version||"
      continue
    fi

    [ "$VERBOSE" = "true" ] && echo -e "  - Latest: ${GREEN}$latest_version${NC}"

    # Compare versions
    comparison=$(compare_versions "$current_version" "$latest_version")
    if [ "$comparison" -eq 0 ]; then
      [ "$VERBOSE" = "true" ] && echo -e "  ${GREEN}✓ Up to date${NC}"
      PROCESSED="${PROCESSED}${addon_name}|up_to_date|$current_version||"
      continue
    elif [ "$comparison" -eq 1 ]; then
      [ "$VERBOSE" = "true" ] && echo -e "  ${YELLOW}⚠ Current version ($current_version) is newer than registry ($latest_version)${NC}"
      PROCESSED="${PROCESSED}${addon_name}|newer_than_registry|$current_version|$latest_version|"
      continue
    fi

    [ "$VERBOSE" = "true" ] && echo -e "  ${YELLOW}⚠ Update available: $current_version → $latest_version${NC}"

    # Skip actual updates in dry run mode
    if [ "$DRY_RUN" = "true" ]; then
      [ "$VERBOSE" = "true" ] && echo -e "  ${BLUE}[DRY RUN] Would update${NC}"
      UPDATED="${UPDATED}${addon_name}|$current_version|$latest_version"
      UPDATED_COUNT=$((UPDATED_COUNT + 1))
      PROCESSED="${PROCESSED}${addon_name}|would_update|$current_version|$latest_version|"
      continue
    fi

    # Update files
    updated_files=0
    
    # Update config.json
    if jq --arg version "$latest_version" '.version = $version' "$config_file" > tmp.json && mv tmp.json "$config_file"; then
      updated_files=$((updated_files+1))
    else
      [ "$VERBOSE" = "true" ] && echo -e "  ${RED}✗ Failed to update config.json${NC}"
    fi
    
    # Update other files if they exist
    for file in build.json update.json; do
      if [ -f "$addon/$file" ]; then
        if jq --arg version "$latest_version" '.version = $version' "$addon/$file" > tmp.json && mv tmp.json "$addon/$file"; then
          updated_files=$((updated_files+1))
        else
          [ "$VERBOSE" = "true" ] && echo -e "  ${RED}✗ Failed to update $file${NC}"
        fi
      fi
    done

    if [ "$updated_files" -eq 0 ]; then
      [ "$VERBOSE" = "true" ] && echo -e "  ${RED}✗ Failed to update files${NC}"
      PROCESSED="${PROCESSED}${addon_name}|update_failed|$current_version|$latest_version|"
      continue
    fi

    # Create or update CHANGELOG.md
    changelog_file="$addon/CHANGELOG.md"
    today=$(date +%Y-%m-%d)
    [ ! -f "$changelog_file" ] && echo "# $addon_name Changelog" > "$changelog_file"
    {
      echo "## $latest_version - $today"
      echo "- Updated from $current_version to $latest_version"
      echo "- [Docker Image](https://hub.docker.com/r/$image_name)"
      echo ""
    } >> "$changelog_file"

    # Add changes to Git
    git add "$config_file" "$changelog_file"
    [ -f "$addon/build.json" ] && git add "$addon/build.json"
    [ -f "$addon/update.json" ] && git add "$addon/update.json"
    
    # Commit changes
    git commit -m "Update $addon_name to $latest_version" >/dev/null
    
    UPDATED="${UPDATED}${addon_name}|$current_version|$latest_version"
    UPDATED_COUNT=$((UPDATED_COUNT + 1))
    PROCESSED="${PROCESSED}${addon_name}|updated|$current_version|$latest_version|"
    [ "$VERBOSE" = "true" ] && echo -e "  ${GREEN}✓ Updated successfully${NC}"
  done

  # Check if no addons were found
  if [ "$CHECKED_COUNT" -eq 0 ]; then
    echo -e "${YELLOW}No addons found in $ADDONS_DIR${NC}"
  fi

  # Return results
  printf "PROCESSED=%s\nUPDATED=%s\nUPDATED_COUNT=%d\nCHECKED_COUNT=%d" "$PROCESSED" "$UPDATED" "$UPDATED_COUNT" "$CHECKED_COUNT"
}

# Run the processing
results=$(process_addons) || true
eval "$results" 2>/dev/null || {
  PROCESSED=""
  UPDATED=""
  UPDATED_COUNT=0
  CHECKED_COUNT=0
}

echo -e "${CYAN}"
echo "===== UPDATE SUMMARY ====="
echo -e "${NC}"
echo -e "Processed: ${BLUE}${CHECKED_COUNT:-0}${NC} addons"
echo -e "Updated:   ${GREEN}${UPDATED_COUNT:-0}${NC} addons"

# Push changes if updates were made
if [ "${UPDATED_COUNT:-0}" -gt 0 ] && [ "$DRY_RUN" = "false" ]; then
  echo -e "${CYAN}"
  echo "===== PUSHING CHANGES ====="
  echo -e "${NC}"
  git push origin $DEFAULT_BRANCH
  echo -e "${GREEN}✓ Changes pushed to repository${NC}"
  echo -e "${BLUE}[Destination]${NC} $REPO_URL (branch: ${CYAN}$DEFAULT_BRANCH${NC})"
  
  # Trigger Home Assistant reload
  if [ -n "$SUPERVISOR_TOKEN" ]; then
    echo -e "${CYAN}===== RELOADING STORE ====="
    curl -s -o /dev/null \
      -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
      -H "Content-Type: application/json" \
      -X POST \
      http://supervisor/store/reload
    echo -e "${GREEN}✓ Store reloaded${NC}"
  else
    echo -e "${YELLOW}⚠ Supervisor token not available${NC}"
  fi
elif [ "$DRY_RUN" = "true" ] && [ "${UPDATED_COUNT:-0}" -gt 0 ]; then
  echo -e "${BLUE}[DRY RUN] Would have pushed ${UPDATED_COUNT} updates to branch: ${CYAN}$DEFAULT_BRANCH${NC}"
fi

# Send Gotify notification if enabled
if [ "$ENABLE_NOTIFICATIONS" = "true" ] && [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
  echo -e "${CYAN}"
  echo "===== SENDING NOTIFICATION ====="
  echo -e "${NC}"
  
  # Prepare message
  message="### Addon Update Report"
  [ "$DRY_RUN" = "true" ] && message="$message (Dry Run)"
  message="$message\n\n"
  message="$message\n#### 🔍 Checked Addons (${CHECKED_COUNT:-0}):\n"
  
  # Parse processed addons
  if [ -n "$PROCESSED" ]; then
    printf "%s" "$PROCESSED" | while IFS='|' read -r name status current latest _; do
      [ -z "$name" ] && continue
      case $status in
        updated) message="$message\n- ✅ **$name**: Updated to $latest" ;;
        would_update) message="$message\n- ⚡ **$name**: Would update to $latest (Dry Run)" ;;
        up_to_date) message="$message\n- ✔️ **$name**: Up-to-date ($current)" ;;
        no_registry_version) message="$message\n- ⚠️ **$name**: No registry version found" ;;
        missing_config) message="$message\n- ❌ **$name**: Missing config.json" ;;
        missing_image) message="$message\n- ❌ **$name**: Missing image name" ;;
        update_failed) message="$message\n- ❌ **$name**: Update failed" ;;
        newer_than_registry) message="$message\n- ⚠️ **$name**: Current ($current) newer than registry ($latest)" ;;
        *) message="$message\n- ❓ **$name**: $status" ;;
      esac
    done
  else
    message="$message\nNo addons were processed"
  fi

  # Add updated section
  if [ "${UPDATED_COUNT:-0}" -gt 0 ]; then
    message="$message\n\n#### 🔄 Updated Addons ($UPDATED_COUNT):\n"
    [ -n "$UPDATED" ] && printf "%s" "$UPDATED" | while IFS='|' read -r name old new; do
      [ -z "$name" ] && continue
      message="$message\n- ➡️ **$name**: $old → $new"
    done
  else
    message="$message\n\n#### 🔄 Updated Addons: No updates"
  fi

  # Add summary
  message="$message\n\n📊 **Summary**: ${UPDATED_COUNT:-0} updated, ${CHECKED_COUNT:-0} checked"
  
  # Send notification
  echo -e "Sending to Gotify: ${BLUE}$GOTIFY_URL${NC}"
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
  echo -e "${GREEN}✓ Notification sent${NC}"
fi

# Calculate and display execution time
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo -e "${CYAN}"
echo "===== COMPLETED IN ${DURATION}s ====="
echo -e "${NC}"
exit 0
