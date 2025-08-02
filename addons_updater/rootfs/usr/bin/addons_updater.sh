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
    # Usage: LOG LEVEL MESSAGE
    LEVEL=$1
    MSG=$2
    COLOR=$GREEN
    case $LEVEL in
        INFO) COLOR=$GREEN ;;
        WARN) COLOR=$YELLOW ;;
        ERROR) COLOR=$RED ;;
        DRYRUN) COLOR=$MAGENTA ;;
    esac
    echo "${COLOR}[$LEVEL]${NC} $MSG"
}

# Read options.json (replace with your method if needed)
OPTIONS_FILE="/data/options.json"
GITUSER=$(jq -r '.gituser // empty' "$OPTIONS_FILE")
GITMAIL=$(jq -r '.gitmail // empty' "$OPTIONS_FILE")
GITAPI=$(jq -r '.gitapi // empty' "$OPTIONS_FILE")
REPOSITORY=$(jq -r '.repository // empty' "$OPTIONS_FILE")
VERBOSE=$(jq -r '.verbose // false' "$OPTIONS_FILE")
DRY_RUN=$(jq -r '.dry_run // false' "$OPTIONS_FILE")
ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications // false' "$OPTIONS_FILE")
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_FILE")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_FILE")
GITEA_API_URL=$(jq -r '.gitea_api_url // empty' "$OPTIONS_FILE")
GITEA_TOKEN=$(jq -r '.gitea_token // empty' "$OPTIONS_FILE")

if [ "$DRY_RUN" = true ]; then
    LOG DRYRUN "Dry run mode enabled. No changes will be pushed."
fi

LOG INFO "===== ADDON UPDATER STARTED ====="
LOG INFO "Repository: $REPOSITORY"

# Setup git config
git config --global user.name "$GITUSER"
if [ -n "$GITMAIL" ]; then
    git config --global user.email "$GITMAIL"
fi

# Prepare repo local path
REPO_NAME=$(basename "$REPOSITORY")
REPO_DIR="/data/$REPO_NAME"

# Clone or update repo
if [ ! -d "$REPO_DIR/.git" ]; then
    LOG INFO "Cloning repository $REPOSITORY..."
    git clone "https://github.com/$REPOSITORY" "$REPO_DIR" || {
        LOG ERROR "Failed to clone repository."
        exit 1
    }
else
    LOG INFO "Repository already exists, updating..."
    cd "$REPO_DIR"
    git fetch origin
    # Check if branch exists, fallback to main if necessary
    git branch --list main > /dev/null 2>&1 && BRANCH=main || BRANCH=$(git branch --list | head -n1 | tr -d '* ')
    git checkout "$BRANCH"
    git reset --hard "origin/$BRANCH"
    git pull origin "$BRANCH"
fi

cd "$REPO_DIR"

# Function: Get latest release tag from GitHub API
get_latest_github_release() {
    repo="$1"
    token="$2"

    auth_header=""
    if [ -n "$token" ] && [ "$token" != "null" ]; then
        auth_header="Authorization: token $token"
    fi

    # Query GitHub API for latest release
    release_json=$(curl -sSL -H "Accept: application/vnd.github+json" -H "$auth_header" "https://api.github.com/repos/$repo/releases/latest")

    # Extract tag_name
    tag_name=$(echo "$release_json" | jq -r '.tag_name // empty')

    # Check if tag_name empty or API error
    if [ -z "$tag_name" ]; then
        LOG WARN "$repo: No latest release found or API limit reached."
        echo ""
        return 1
    fi

    echo "$tag_name"
}

# Process each addon directory that has updater.json
for addon_dir in */; do
    if [ -f "$addon_dir/updater.json" ]; then
        SLUG=${addon_dir%/}
        LOG INFO "Processing addon $SLUG..."

        UPSTREAM=$(jq -r .upstream_repo "$addon_dir/updater.json")
        SOURCE=$(jq -r .source "$addon_dir/updater.json")
        PAUSED=$(jq -r .paused "$addon_dir/updater.json")
        CURRENT_VERSION=$(jq -r .upstream_version "$addon_dir/updater.json")
        FILTER_TEXT=$(jq -r .github_tagfilter "$addon_dir/updater.json")
        EXCLUDE_TEXT=$(jq -r .github_exclude "$addon_dir/updater.json")
        BYDATE=$(jq -r .dockerhub_by_date "$addon_dir/updater.json")

        if [ "$PAUSED" = "true" ]; then
            LOG WARN "$SLUG: Updates paused, skipping."
            continue
        fi

        # Get latest version based on source
        LATEST_VERSION=""
        if [ "$SOURCE" = "github" ]; then
            # GitHub source, use API
            LATEST_VERSION=$(get_latest_github_release "$UPSTREAM" "$GITAPI") || true
        elif [ "$SOURCE" = "dockerhub" ]; then
            # DockerHub source
            DOCKERHUB_REPO="${UPSTREAM%%/*}"
            DOCKERHUB_IMAGE=$(echo "$UPSTREAM" | cut -d "/" -f2)
            LISTSIZE=100
            FILTER_QUERY=""
            EXCLUDE_PATTERN="${EXCLUDE_TEXT:-zzzzzzzzzzzzzzzzzz}"

            if [ "$FILTER_TEXT" != "null" ] && [ -n "$FILTER_TEXT" ]; then
                FILTER_QUERY="&name=$FILTER_TEXT"
            fi

            LATEST_VERSION=$(
                curl -f -L -s "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=${LISTSIZE}${FILTER_QUERY}" \
                | jq -r '.results | .[] | .name' \
                | grep -v -e latest -e dev -e nightly -e beta \
                | grep -v "$EXCLUDE_PATTERN" \
                | sort -V \
                | tail -n 1
            )
        else
            LOG WARN "$SLUG: Unsupported source $SOURCE, skipping."
            continue
        fi

        if [ -z "$LATEST_VERSION" ]; then
            LOG WARN "$SLUG: No latest version found, skipping."
            continue
        fi

        if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
            LOG INFO "$SLUG: Update available: $CURRENT_VERSION -> $LATEST_VERSION"

            if [ "$DRY_RUN" != true ]; then
                # Update version in files
                for file in "$addon_dir"/config.json "$addon_dir"/build.json "$addon_dir"/updater.json; do
                    if [ -f "$file" ]; then
                        jq --arg v "$LATEST_VERSION" '.version = $v | .upstream_version = $v' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
                    fi
                done

                # Update changelog
                CHANGELOG="$addon_dir/CHANGELOG.md"
                touch "$CHANGELOG"
                DATE=$(date '+%Y-%m-%d')
                sed -i "1i\n## $LATEST_VERSION ($DATE)\n- Updated to latest version from $UPSTREAM\n" "$CHANGELOG"

                # Git commit and push
                git add -A
                git commit -m "Updater bot: $SLUG updated to $LATEST_VERSION" || true
                git push origin "$BRANCH" || LOG WARN "$SLUG: git push failed."

                LOG INFO "$SLUG: Updated to $LATEST_VERSION and pushed changes."
            else
                LOG DRYRUN "$SLUG: Update simulated from $CURRENT_VERSION to $LATEST_VERSION."
            fi

            # TODO: Notification logic (Gotify, Gitea) can be triggered here if ENABLE_NOTIFICATIONS=true

        else
            LOG INFO "$SLUG: Already up to date ($CURRENT_VERSION)."
        fi
    fi
done

LOG INFO "===== ADDON UPDATER FINISHED ====="

exit 0
