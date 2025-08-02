#!/bin/sh
set -e

# Fix missing HOME variable to prevent git errors
export HOME=/tmp

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

# Load options.json
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

# Configure git user/email globally
git config --global user.name "$GITUSER"
if [ -n "$GITMAIL" ] && [ "$GITMAIL" != "null" ]; then
    git config --global user.email "$GITMAIL"
fi

REPO_NAME=$(basename "$REPOSITORY")
REPO_DIR="/data/$REPO_NAME"

# Clone or update repository
if [ ! -d "$REPO_DIR/.git" ]; then
    LOG INFO "Cloning repository $REPOSITORY..."
    if ! git clone "https://github.com/$REPOSITORY" "$REPO_DIR"; then
        LOG ERROR "Failed to clone repository."
        exit 1
    fi
else
    LOG INFO "Repository already exists, updating..."
    cd "$REPO_DIR"
    git fetch origin || LOG WARN "Git fetch failed"
    # Detect main branch fallback to master
    if git show-ref --verify --quiet refs/heads/main; then
        BRANCH="main"
    else
        BRANCH="master"
    fi
    git checkout "$BRANCH" || LOG WARN "Git checkout $BRANCH failed"
    git reset --hard "origin/$BRANCH"
    git pull origin "$BRANCH" || LOG WARN "Git pull failed"
fi

cd "$REPO_DIR"

# Function to get latest GitHub release tag
get_latest_github_release() {
    repo="$1"
    token="$2"

    auth_header=""
    if [ -n "$token" ] && [ "$token" != "null" ]; then
        auth_header="Authorization: token $token"
    fi

    release_json=$(curl -sSL -H "Accept: application/vnd.github+json" -H "$auth_header" "https://api.github.com/repos/$repo/releases/latest")

    tag_name=$(echo "$release_json" | jq -r '.tag_name // empty')

    if [ -z "$tag_name" ]; then
        LOG WARN "$repo: No latest release found or API limit reached."
        echo ""
        return 1
    fi

    echo "$tag_name"
}

# Function to send Gotify notification
send_gotify() {
    if [ "$ENABLE_NOTIFICATIONS" = true ] && [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
        TITLE="$1"
        MESSAGE="$2"
        PRIORITY="${3:-5}"

        curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"title\":\"$TITLE\", \"message\":\"$MESSAGE\", \"priority\":$PRIORITY}" >/dev/null 2>&1
    fi
}

# Function to send Gitea notification (example placeholder)
send_gitea() {
    if [ "$ENABLE_NOTIFICATIONS" = true ] && [ -n "$GITEA_API_URL" ] && [ -n "$GITEA_TOKEN" ]; then
        # Example: POST a comment or notification to Gitea API here
        # This is a placeholder — implement as needed
        :
    fi
}

# Function to update changelog file (prepend new version section)
update_changelog() {
    local changelog_file=$1
    local version=$2
    local url=$3

    DATE=$(date '+%Y-%m-%d')

    # Use sed to prepend (POSIX compatible)
    sed -i "1i\\
## $version ($DATE)\\
- Updated to latest version ($version) from $url\\
" "$changelog_file"
}

# Main update loop
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

        LATEST_VERSION=""
        if [ "$SOURCE" = "github" ]; then
            LATEST_VERSION=$(get_latest_github_release "$UPSTREAM" "$GITAPI") || true
        elif [ "$SOURCE" = "dockerhub" ]; then
            # Docker Hub tags retrieval, with filters
            DOCKERHUB_REPO=$(echo "$UPSTREAM" | cut -d "/" -f1)
            DOCKERHUB_IMAGE=$(echo "$UPSTREAM" | cut -d "/" -f2-)
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
                # Update config files
                for file in "$addon_dir"/config.json "$addon_dir"/build.json "$addon_dir"/updater.json; do
                    if [ -f "$file" ]; then
                        jq --arg v "$LATEST_VERSION" '.version = $v | .upstream_version = $v' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
                    fi
                done

                # Update changelog
                CHANGELOG="$addon_dir/CHANGELOG.md"
                if [ ! -f "$CHANGELOG" ]; then
                    touch "$CHANGELOG"
                fi
                update_changelog "$CHANGELOG" "$LATEST_VERSION" "$UPSTREAM"

                # Commit and push changes
                git add -A
                git commit -m "Updater bot: $SLUG updated to $LATEST_VERSION" || true
                git push origin "$BRANCH" || LOG WARN "$SLUG: git push failed."

                LOG INFO "$SLUG: Updated to $LATEST_VERSION and pushed changes."

                # Send notifications if enabled
                if [ "$ENABLE_NOTIFICATIONS" = true ]; then
                    MSG="Addon $SLUG updated to version $LATEST_VERSION."
                    send_gotify "Addon Update" "$MSG"
                    send_gitea "$MSG"
                fi
            else
                LOG DRYRUN "$SLUG: Update simulated from $CURRENT_VERSION to $LATEST_VERSION."
            fi
        else
            LOG INFO "$SLUG: Already up to date ($CURRENT_VERSION)."
        fi
    fi
done

LOG INFO "===== ADDON UPDATER FINISHED ====="

exit 0
