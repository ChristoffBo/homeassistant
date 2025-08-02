#!/bin/sh
set -e

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Log function with dry-run awareness
LOG() {
    level=$(echo "$1" | tr '[:lower:]' '[:upper:]')
    shift
    message="$*"

    if [ "$DRY_RUN" = "true" ]; then
        case "$level" in
            INFO) printf "%b[DRY RUN INFO]%b %s\n" "$MAGENTA" "$NC" "$message" ;;
            WARN) printf "%b[DRY RUN WARN]%b %s\n" "$MAGENTA" "$NC" "$message" ;;
            ERROR) printf "%b[DRY RUN ERROR]%b %s\n" "$MAGENTA" "$NC" "$message" ;;
            *) printf "%b[DRY RUN]%b %s\n" "$MAGENTA" "$NC" "$message" ;;
        esac
    else
        case "$level" in
            INFO) printf "%b[INFO]%b %s\n" "$GREEN" "$NC" "$message" ;;
            WARN) printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$message" ;;
            ERROR) printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$message" ;;
            *) printf "%b[INFO]%b %s\n" "$CYAN" "$NC" "$message" ;;
        esac
    fi
}

# Load config from secure source or environment variables here:
GITUSER="your-git-username"
GITMAIL="your-email@example.com"
GITAPI="your-github-token"  # Use GitHub token securely (e.g., secrets, env vars)
REPOSITORY="yourusername/yourrepo"
VERBOSE=true
DRY_RUN=true
NOTIFICATIONS_ENABLED=true

# Export GitHub token for git usage
export GITHUB_API_TOKEN="$GITAPI"

LOG INFO "===== ADDON UPDATER STARTED ====="
LOG INFO "Dry run mode: $DRY_RUN"
LOG INFO "Repository: $REPOSITORY"

# Prepare repo directory
REPO_DIR="/data/$(basename "$REPOSITORY")"

if [ ! -d "$REPO_DIR" ]; then
    LOG INFO "Cloning repository $REPOSITORY (shallow)..."
    git clone --depth=1 "https://github.com/$REPOSITORY.git" "$REPO_DIR" || {
        LOG ERROR "Failed to clone repository"
        exit 1
    }
else
    LOG INFO "Repository exists, pulling latest changes..."
    cd "$REPO_DIR" || exit 1
    git pull --rebase origin main || {
        LOG WARN "Git pull failed, attempting hard reset..."
        git reset --hard origin/main || {
            LOG ERROR "Reset failed. Removing repo and recloning..."
            cd /data || exit 1
            rm -rf "$REPO_DIR"
            git clone --depth=1 "https://github.com/$REPOSITORY.git" "$REPO_DIR" || {
                LOG ERROR "Failed to clone repository"
                exit 1
            }
        }
    }
fi

cd "$REPO_DIR" || exit 1

# Iterate over addon directories (folders with updater.json)
for addon_dir in */ ; do
    addon=${addon_dir%/}

    if [ ! -f "$addon_dir/updater.json" ]; then
        LOG WARN "Addon $addon missing updater.json, skipping."
        continue
    fi

    UPSTREAM=$(jq -r '.upstream_repo // empty' "$addon_dir/updater.json")
    BETA=$(jq -r '.github_beta // false' "$addon_dir/updater.json")
    FULLTAG=$(jq -r '.github_fulltag // false' "$addon_dir/updater.json")
    HAVINGASSET=$(jq -r '.github_havingasset // false' "$addon_dir/updater.json")
    SOURCE=$(jq -r '.source // empty' "$addon_dir/updater.json")
    FILTER_TEXT=$(jq -r '.github_tagfilter // empty' "$addon_dir/updater.json")
    EXCLUDE_TEXT=$(jq -r '.github_exclude // ""' "$addon_dir/updater.json")
    PAUSED=$(jq -r '.paused // false' "$addon_dir/updater.json")
    CURRENT=$(jq -r '.upstream_version // empty' "$addon_dir/updater.json")
    LISTSIZE=$(jq -r '.dockerhub_list_size // 100' "$addon_dir/updater.json")
    BYDATE=$(jq -r '.dockerhub_by_date // false' "$addon_dir/updater.json")

    if [ "$PAUSED" = "true" ]; then
        LOG INFO "$addon updates are paused, skipping."
        continue
    fi

    if [ -z "$UPSTREAM" ] || [ -z "$SOURCE" ]; then
        LOG WARN "$addon missing upstream_repo or source in updater.json, skipping."
        continue
    fi

    LOG INFO "Checking updates for addon $addon (current version: $CURRENT)..."

    LASTVERSION=""

    if [ "$SOURCE" = "dockerhub" ]; then
        REPO_NAME=$(echo "$UPSTREAM" | cut -d '/' -f1)
        IMAGE_NAME=$(echo "$UPSTREAM" | cut -d '/' -f2)

        FILTER_PARAM=""
        if [ -n "$FILTER_TEXT" ] && [ "$FILTER_TEXT" != "null" ]; then
            FILTER_PARAM="&name=$FILTER_TEXT"
        fi

        EXCLUDE_PATTERN="zzzzzzzzzzzzzzzzzz"
        if [ -n "$EXCLUDE_TEXT" ] && [ "$EXCLUDE_TEXT" != "null" ]; then
            EXCLUDE_PATTERN="$EXCLUDE_TEXT"
        fi

        LASTVERSION=$(curl -s "https://hub.docker.com/v2/repositories/$REPO_NAME/$IMAGE_NAME/tags?page_size=$LISTSIZE$FILTER_PARAM" | \
            jq -r '.results[].name' | \
            grep -v -E "latest|dev|nightly|beta|$EXCLUDE_PATTERN" | \
            sort -V | tail -n1)

        if [ "$BETA" = "true" ]; then
            LASTVERSION=$(curl -s "https://hub.docker.com/v2/repositories/$REPO_NAME/$IMAGE_NAME/tags?page_size=$LISTSIZE$FILTER_PARAM" | \
                jq -r '.results[].name' | \
                grep -E "dev" | \
                grep -v "$EXCLUDE_PATTERN" | \
                sort -V | tail -n1)
        fi

        if [ "$BYDATE" = "true" ]; then
            LASTVERSION=$(curl -s "https://hub.docker.com/v2/repositories/$REPO_NAME/$IMAGE_NAME/tags?page_size=$LISTSIZE&ordering=last_updated$FILTER_PARAM" | \
                jq -r '.results[].name' | \
                grep -v -E "latest|dev|nightly|beta|$EXCLUDE_PATTERN" | \
                sort -V | tail -n1)
        fi

    else
        ARGUMENTS="--at $SOURCE"
        [ "$FULLTAG" = "true" ] && ARGUMENTS="$ARGUMENTS --format tag"
        [ "$HAVINGASSET" = "true" ] && ARGUMENTS="$ARGUMENTS --having-asset"
        [ -n "$FILTER_TEXT" ] && [ "$FILTER_TEXT" != "null" ] && ARGUMENTS="$ARGUMENTS --only $FILTER_TEXT"
        [ -n "$EXCLUDE_TEXT" ] && [ "$EXCLUDE_TEXT" != "null" ] && ARGUMENTS="$ARGUMENTS --exclude $EXCLUDE_TEXT"
        [ "$BETA" = "true" ] && ARGUMENTS="$ARGUMENTS --pre"

        LASTVERSION=$(lastversion "$UPSTREAM" $ARGUMENTS || true)
    fi

    CLEAN_LAST=$(echo "$LASTVERSION" | tr -d '"')
    CLEAN_CURR=$(echo "$CURRENT" | tr -d '"')

    if [ "$CLEAN_LAST" != "" ] && [ "$CLEAN_LAST" != "$CLEAN_CURR" ]; then
        LOG INFO "Addon $addon: update available from $CURRENT to $LASTVERSION"

        if [ "$DRY_RUN" = "true" ]; then
            LOG INFO "[DRY RUN] Would update $addon from $CURRENT to $LASTVERSION"
        else
            for file in config.json build.json updater.json; do
                if [ -f "$addon_dir/$file" ]; then
                    sed -i "s/$CURRENT/$LASTVERSION/g" "$addon_dir/$file"
                fi
            done

            if [ -f "$addon_dir/config.json" ]; then
                jq --arg ver "$CLEAN_LAST" '.version = $ver' "$addon_dir/config.json" > "$addon_dir/config.tmp.json" && mv "$addon_dir/config.tmp.json" "$addon_dir/config.json"
            fi

            DATE=$(date '+%Y-%m-%d')
            jq --arg ver "$CLEAN_LAST" --arg date "$DATE" \
                '.upstream_version = $ver | .last_update = $date' \
                "$addon_dir/updater.json" > "$addon_dir/updater.tmp.json" && mv "$addon_dir/updater.tmp.json" "$addon_dir/updater.json"

            CHANGELOG="$addon_dir/CHANGELOG.md"
            [ ! -f "$CHANGELOG" ] && touch "$CHANGELOG"
            printf "## %s (%s)\n- Update to version %s from %s\n\n" "$CLEAN_LAST" "$DATE" "$CLEAN_LAST" "$UPSTREAM" | cat - "$CHANGELOG" > "$CHANGELOG.tmp" && mv "$CHANGELOG.tmp" "$CHANGELOG"

            cd "$REPO_DIR" || exit 1
            git add "$addon_dir"
            git commit -m "Updater bot: $addon updated to $CLEAN_LAST"
            if [ "$DRY_RUN" = "true" ]; then
                LOG INFO "[DRY RUN] Would push changes to remote repository."
            else
                git push origin main
                LOG INFO "Changes pushed to remote repository."
            fi
        fi
    else
        LOG INFO "Addon $addon is up to date ($CURRENT)."
    fi
done

LOG INFO "===== ADDON UPDATER FINISHED ====="
