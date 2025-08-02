#!/bin/sh
set -e

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

LOG() {
    level="$1"
    msg="$2"
    now=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

    # Different color for dry run logs
    if [ "$DRY_RUN" = "true" ]; then
        # Dry run uses MAGENTA for info, YELLOW for warnings, RED for errors
        case "$level" in
            INFO) color="$MAGENTA" ;;
            WARN) color="$YELLOW" ;;
            ERROR) color="$RED" ;;
            *) color="$NC" ;;
        esac
        prefix="[DRY RUN]"
    else
        # Live run uses CYAN for info, YELLOW for warnings, RED for errors
        case "$level" in
            INFO) color="$CYAN" ;;
            WARN) color="$YELLOW" ;;
            ERROR) color="$RED" ;;
            *) color="$NC" ;;
        esac
        prefix=""
    fi

    printf "%b[%s] %s%s: %s%b\n" "$color" "$now" "$prefix" "$level" "$msg" "$NC"
}

# Load config
CONFIG_FILE="/data/options.json"

GITHUB_USERNAME=$(jq -r '.gituser // empty' "$CONFIG_FILE")
GITHUB_EMAIL=$(jq -r '.gitmail // empty' "$CONFIG_FILE")
GITHUB_TOKEN=$(jq -r '.gitapi // empty' "$CONFIG_FILE")
GITHUB_REPO=$(jq -r '.repository // empty' "$CONFIG_FILE")

VERBOSE=$(jq -r '.verbose // false' "$CONFIG_FILE")
DRY_RUN=$(jq -r '.dry_run // false' "$CONFIG_FILE")
ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications // false' "$CONFIG_FILE")

GOTIFY_URL=$(jq -r '.gotify_url // empty' "$CONFIG_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$CONFIG_FILE")

if [ -z "$GITHUB_REPO" ]; then
    LOG ERROR "GitHub repository not configured in options.json"
    exit 1
fi

[ "$VERBOSE" = "true" ] && LOG INFO "Config loaded: repo=$GITHUB_REPO, dry_run=$DRY_RUN, notifications=$ENABLE_NOTIFICATIONS"

REPO_DIR="/data/repo"

git_clone_or_pull() {
    if [ ! -d "$REPO_DIR/.git" ]; then
        LOG INFO "Cloning repo $GITHUB_REPO (shallow)..."
        if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
            git clone --depth 1 "https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git" "$REPO_DIR"
        else
            git clone --depth 1 "https://github.com/${GITHUB_REPO}.git" "$REPO_DIR"
        fi
        LOG INFO "Repository cloned."
    else
        LOG INFO "Updating repo $GITHUB_REPO..."
        cd "$REPO_DIR"
        git fetch --depth 1 origin
        git reset --hard origin/$(git rev-parse --abbrev-ref HEAD)
        cd -
        LOG INFO "Repository updated."
    fi
}

# Normalize Docker tag by stripping arch prefixes (amd64-, armhf-, etc)
normalize_tag() {
    echo "$1" | sed -E 's/^(amd64|armhf|armv7|aarch64|arm64|x86_64|ppc64le|s390x)-//'
}

# Compare semantic versions: return 0 if v1 < v2, else 1
ver_lt() {
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" != "$2" ]
}

# Dummy fetch_latest_tag function: Replace with real Docker Hub / GHCR / LinuxServer API calls
fetch_latest_tag() {
    image="$1"
    registry="$2"
    # Placeholder - always return 1.0.0 for demonstration
    echo "1.0.0"
}

send_gotify() {
    title="$1"
    message="$2"
    if [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
        curl -s -X POST "$GOTIFY_URL/message" \
             -H "X-Gotify-Key: $GOTIFY_TOKEN" \
             -d "title=$title" \
             -d "message=$message" \
             -d "priority=5"
        LOG INFO "Gotify notification sent: $title"
    else
        LOG WARN "Gotify URL or token missing; cannot send notification."
    fi
}

update_addon() {
    addon_path="$1"
    addon_name=$(basename "$addon_path")

    current_version=$(jq -r '.version // empty' "$addon_path/config.json")
    image=$(jq -r '.image // empty' "$addon_path/config.json")

    if [ -z "$image" ]; then
        LOG WARN "Addon $addon_name missing image field, skipping."
        return
    fi

    # Determine registry type
    if echo "$image" | grep -q "^ghcr.io/"; then
        registry="ghcr"
        image_name=$(echo "$image" | sed 's/^ghcr.io\///')
    elif echo "$image" | grep -q "^linuxserver/"; then
        registry="linuxserver"
        image_name="$image"
    else
        registry="dockerhub"
        image_name="$image"
    fi

    latest_version=$(fetch_latest_tag "$image_name" "$registry")

    if [ "$latest_version" = "latest" ] || [ -z "$latest_version" ]; then
        LOG WARN "Addon $addon_name: Could not fetch latest version, skipping."
        return
    fi

    norm_current=$(normalize_tag "$current_version")
    norm_latest=$(normalize_tag "$latest_version")

    if ver_lt "$norm_current" "$norm_latest"; then
        LOG INFO "Addon $addon_name: Update available $current_version -> $latest_version"
        if [ "$DRY_RUN" = "true" ]; then
            LOG INFO "Dry run: Simulated update for $addon_name - would update version to $latest_version"
            # Simulate changelog append
            LOG INFO "Dry run: Would append to CHANGELOG.md with update info"
            return
        fi

        # Perform real update
        jq ".version = \"$latest_version\"" "$addon_path/config.json" > "$addon_path/config.json.tmp" && mv "$addon_path/config.json.tmp" "$addon_path/config.json"

        changelog="$addon_path/CHANGELOG.md"
        date_now=$(date -u +"%Y-%m-%d")
        echo "## [$latest_version] - $date_now" >> "$changelog"
        echo "- Updated from $current_version to $latest_version" >> "$changelog"

        # Commit changes
        cd "$REPO_DIR"
        git add "$addon_name/config.json" "$addon_name/CHANGELOG.md"
        git commit -m "Update $addon_name to version $latest_version" || true
        cd -

        # Send notifications if enabled
        if [ "$ENABLE_NOTIFICATIONS" = "true" ]; then
            send_gotify "Addon Update" "$addon_name updated to $latest_version"
        fi

    else
        LOG INFO "Addon $addon_name: Already at latest version ($current_version)"
    fi
}

# Main execution

LOG INFO "===== ADDON UPDATER STARTED ====="
if [ "$DRY_RUN" = "true" ]; then
    LOG INFO "Running in DRY RUN mode. No changes will be made."
else
    LOG INFO "Running in LIVE mode. Updates will be applied."
fi

git_clone_or_pull

if [ ! -d "$REPO_DIR" ]; then
    LOG ERROR "Repository directory missing after clone/pull."
    exit 1
fi

for addon_dir in "$REPO_DIR"/*; do
    if [ -d "$addon_dir" ] && [ -f "$addon_dir/config.json" ]; then
        update_addon "$addon_dir"
    fi
done

LOG INFO "===== ADDON UPDATER FINISHED ====="

exit 0
