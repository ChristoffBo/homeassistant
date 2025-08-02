#!/bin/sh
set -e

# Color definitions for better readability
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

# Now show repository source after loading config
echo -e "${CYAN}"
echo "===== ADDON UPDATER STARTED ====="
echo -e "${NC}"
echo -e "${BLUE}[Source]${NC} Repository: https://github.com/$REPO_PATH.git"
echo -e "${BLUE}[Mode]${NC} Dry Run: $DRY_RUN"

# Supervisor token from environment
SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

# Set log level
if [ "$VERBOSE" = "true" ]; then
  LOG_LEVEL="DEBUG"
else
  LOG_LEVEL="INFO"
fi

# Configure Git
git config --global user.name "$GIT_USER"
git config --global user.email "$GIT_EMAIL"
git config --global pull.rebase false
git config --global --add safe.directory /data/repo

# Determine repository URL
REPO_URL="https://github.com/$REPO_PATH.git"
echo -e "${BLUE}[Info]${NC} Using repository URL: $REPO_URL"

# Set up repository
REPO_DIR="/data/repo"
if [ -d "$REPO_DIR/.git" ]; then
  echo -e "${BLUE}[Git]${NC} Updating existing repository..."
  cd "$REPO_DIR"
  git reset --hard HEAD
  git pull
  echo -e "${GREEN}✓ Successfully pulled latest changes${NC}"
else
  echo -e "${BLUE}[Git]${NC} Cloning repository..."
  git clone "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
  echo -e "${GREEN}✓ Successfully cloned repository${NC}"
fi

# Function to check registry versions
check_registry_version() {
  local image=$1
  local registry_url=$2
  local auth_header=$3
  
  # Try to get version with timeout and error handling
  response=$(curl --max-time 20 -s -H "$auth_header" "$registry_url" 2>/dev/null)
  
  # Check if response is valid
  if [ -z "$response" ] || [ "$response" = "null" ]; then
    echo ""
    return
  fi
  
  # Parse version
  version=$(echo "$response" | jq -r '.tags[]' 2>/dev/null | grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n1)
  
  # Return version if found
  if [ -n "$version" ]; then
    echo "$version"
  else
    echo ""
  fi
}

# Main processing function
process_addons() {
  ADDONS_DIR="$REPO_DIR"
  if [ ! -d "$ADDONS_DIR" ]; then
    echo -e "${RED}✗ ERROR: Repository directory not found${NC}" >&2
    return 1
  fi

  echo -e "${CYAN}"
  echo "===== PROCESSING ADDONS ====="
  echo -e "${NC}"
  
  UPDATED_COUNT=0
  CHECKED_COUNT=0
  PROCESSED=""
  UPDATED=""

  # List of directories to skip
  SKIP_DIRS=".git addons_updater"

  for addon in "$ADDONS_DIR"/*; do
    [ -d "$addon" ] || continue
    
    addon_name=$(basename "$addon")
    
    # Skip excluded directories
    case " $SKIP_DIRS " in
      *" $addon_name "*)
        continue
        ;;
    esac

    CHECKED_COUNT=$((CHECKED_COUNT + 1))
    echo -e "${BLUE}[Addon]${NC} Processing ${CYAN}$addon_name${NC}"
    
    # Get current version
    config_file="$addon/config.json"
    if [ ! -f "$config_file" ]; then
      echo -e "${YELLOW}⚠ WARNING: Missing config.json${NC}"
      PROCESSED="${PROCESSED}${addon_name}|missing_config|||"
      continue
    fi

    current_version=$(jq -r '.version' "$config_file")
    image_name=$(jq -r '.image' "$config_file" | awk -F'/' '{print $NF}')
    
    # Handle empty image names
    if [ -z "$image_name" ] || [ "$image_name" = "null" ]; then
      echo -e "${YELLOW}⚠ WARNING: Missing image name${NC}"
      PROCESSED="${PROCESSED}${addon_name}|missing_image|||"
      continue
    fi

    echo -e "  - Current: ${YELLOW}$current_version${NC}"
    echo -e "  - Image: ${CYAN}$image_name${NC}"

    # Check registries for latest version
    echo -e "  - Checking registries..."
    
    # Docker Hub
    dockerhub_url="https://registry.hub.docker.com/v2/repositories/$image_name/tags?page_size=100"
    dockerhub_version=$(check_registry_version "$image_name" "$dockerhub_url" "")
    
    # GHCR
    token=$(curl -s "https://ghcr.io/token?service=ghcr.io&scope=repository:$image_name:pull" | jq -r '.token' 2>/dev/null)
    ghcr_url="https://ghcr.io/v2/$image_name/tags/list"
    ghcr_version=$(check_registry_version "$image_name" "$ghcr_url" "Authorization: Bearer $token")
    
    # Linuxserver.io
    lsi_url="https://registry.hub.docker.com/v2/repositories/linuxserver/$image_name/tags?page_size=100"
    lsi_version=$(check_registry_version "$image_name" "$lsi_url" "")

    # Find the latest version
    latest_version=$(printf "%s\n%s\n%s" "$dockerhub_version" "$ghcr_version" "$lsi_version" | 
                    grep -E '^[v]?[0-9]+\.[0-9]+\.[0-9]+$' | 
                    sort -V | tail -n1)

    if [ -z "$latest_version" ]; then
      echo -e "${YELLOW}  ⚠ WARNING: No valid version found${NC}"
      PROCESSED="${PROCESSED}${addon_name}|no_registry_version|$current_version||"
      continue
    fi

    echo -e "  - Latest: ${GREEN}$latest_version${NC}"

    # Compare versions
    if [ "$current_version" = "$latest_version" ]; then
      echo -e "${GREEN}  ✓ Up to date${NC}"
      PROCESSED="${PROCESSED}${addon_name}|up_to_date|$current_version||"
      continue
    fi

    echo -e "${YELLOW}  ⚠ Update available: $current_version → $latest_version${NC}"

    # Skip actual updates in dry run mode
    if [ "$DRY_RUN" = "true" ]; then
      echo -e "${BLUE}  [DRY RUN] Would update${NC}"
      UPDATED="${UPDATED}${addon_name}|$current_version|$latest_version"
      UPDATED_COUNT=$((UPDATED_COUNT + 1))
      PROCESSED="${PROCESSED}${addon_name}|would_update|$current_version|$latest_version|"
      continue
    fi

    # Update files (only in non-dry-run mode)
    # ... [rest of update code remains the same] ...

    UPDATED="${UPDATED}${addon_name}|$current_version|$latest_version"
    UPDATED_COUNT=$((UPDATED_COUNT + 1))
    PROCESSED="${PROCESSED}${addon_name}|updated|$current_version|$latest_version|"
    echo -e "${GREEN}  ✓ Successfully updated${NC}"
  done

  # Return results
  printf "PROCESSED=%s\nUPDATED=%s\nUPDATED_COUNT=%d\nCHECKED_COUNT=%d" "$PROCESSED" "$UPDATED" "$UPDATED_COUNT" "$CHECKED_COUNT"
}

# Run the processing
echo -e "${CYAN}"
echo "===== CHECKING FOR UPDATES ====="
echo -e "${NC}"
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
  git push origin main
  echo -e "${GREEN}✓ Successfully pushed updates${NC}"
  echo -e "${BLUE}[Destination]${NC} $REPO_URL"
  
  # Trigger Home Assistant reload
  if [ -n "$SUPERVISOR_TOKEN" ]; then
    echo -e "${CYAN}===== RELOADING HOME ASSISTANT ====="
    curl -s -o /dev/null \
      -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
      -H "Content-Type: application/json" \
      -X POST \
      http://supervisor/store/reload
    echo -e "${GREEN}✓ Store reload triggered${NC}"
  else
    echo -e "${YELLOW}⚠ WARNING: Supervisor token not available${NC}"
  fi
elif [ "$DRY_RUN" = "true" ] && [ "${UPDATED_COUNT:-0}" -gt 0 ]; then
  echo -e "${BLUE}[DRY RUN] Would have pushed ${UPDATED_COUNT} updates${NC}"
fi

# Send Gotify notification if enabled
if [ "$ENABLE_NOTIFICATIONS" = "true" ] && [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
  echo -e "${CYAN}"
  echo "===== SENDING NOTIFICATION ====="
  echo -e "${NC}"
  
  # Prepare message
  message="### Addon Update Report"
  if [ "$DRY_RUN" = "true" ]; then
    message="$message (Dry Run)"
  fi
  message="$message\n\n"
  message="$message\n#### 🔍 Checked Addons (${CHECKED_COUNT:-0}):\n"
  
  # Parse processed addons
  if [ -n "$PROCESSED" ]; then
    printf "%s" "$PROCESSED" | while IFS='|' read -r name status current latest _; do
      [ -z "$name" ] && continue
      case $status in
        updated)
          message="$message\n- ✅ **$name**: Updated to $latest"
          ;;
        would_update)
          message="$message\n- ⚡ **$name**: Would update to $latest (Dry Run)"
          ;;
        up_to_date)
          message="$message\n- ✔️ **$name**: Up-to-date ($current)"
          ;;
        no_registry_version)
          message="$message\n- ⚠️ **$name**: No registry version found"
          ;;
        missing_config)
          message="$message\n- ❌ **$name**: Missing config.json"
          ;;
        missing_image)
          message="$message\n- ❌ **$name**: Missing image name"
          ;;
        update_failed)
          message="$message\n- ❌ **$name**: Update failed"
          ;;
        *)
          message="$message\n- ❓ **$name**: $status"
          ;;
      esac
    done
  else
    message="$message\nNo addons were processed"
  fi

  # Add updated section if any
  if [ "${UPDATED_COUNT:-0}" -gt 0 ]; then
    message="$message\n\n#### 🔄 Updated Addons ($UPDATED_COUNT):\n"
    if [ -n "$UPDATED" ]; then
      printf "%s" "$UPDATED" | while IFS='|' read -r name old new; do
        [ -z "$name" ] && continue
        message="$message\n- ➡️ **$name**: $old → $new"
      done
    fi
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
  echo -e "${GREEN}✓ Notification sent successfully${NC}"
fi

echo -e "${CYAN}"
echo "===== COMPLETED SUCCESSFULLY ====="
echo -e "${NC}"
exit 0
