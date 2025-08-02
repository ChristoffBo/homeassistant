#!/bin/sh
set -e

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

log() {
    # $1 = level (INFO, WARN, ERROR)
    # $2 = message
    # $3 = dry_run flag (optional)

    DRY_RUN=${3:-false}
    PREFIX=""
    COLOR=$NC

    case "$1" in
        INFO) 
            COLOR=$GREEN
            PREFIX="INFO"
            ;;
        WARN)
            COLOR=$YELLOW
            PREFIX="WARN"
            ;;
        ERROR)
            COLOR=$RED
            PREFIX="ERROR"
            ;;
        DRYRUN)
            COLOR=$MAGENTA
            PREFIX="DRYRUN"
            ;;
        *)
            COLOR=$NC
            PREFIX="$1"
            ;;
    esac

    if [ "$DRY_RUN" = true ]; then
        printf "%b[%s][%s] %s%b\n" "$COLOR" "$PREFIX" "DRYRUN" "$2" "$NC"
    else
        printf "%b[%s] %s%b\n" "$COLOR" "$PREFIX" "$2" "$NC"
    fi
}

# Load config.json options
CONFIG_FILE="/data/options.json"

gituser=$(jq -r '.gituser // empty' "$CONFIG_FILE")
gitmail=$(jq -r '.gitmail // empty' "$CONFIG_FILE")
gitapi=$(jq -r '.gitapi // empty' "$CONFIG_FILE")
repository=$(jq -r '.repository // empty' "$CONFIG_FILE")
verbose=$(jq -r '.verbose // false' "$CONFIG_FILE")
dry_run=$(jq -r '.dry_run // false' "$CONFIG_FILE")
enable_notifications=$(jq -r '.enable_notifications // false' "$CONFIG_FILE")
gotify_url=$(jq -r '.gotify_url // empty' "$CONFIG_FILE")
gotify_token=$(jq -r '.gotify_token // empty' "$CONFIG_FILE")
gitea_api_url=$(jq -r '.gitea_api_url // empty' "$CONFIG_FILE")
gitea_token=$(jq -r '.gitea_token // empty' "$CONFIG_FILE")

if [ -z "$repository" ]; then
    log ERROR "No repository configured in options.json. Exiting."
    exit 1
fi

# Set HOME if unset (fix git errors)
export HOME=${HOME:-/tmp}

log DRYRUN "===== ADDON UPDATER STARTED =====" "$dry_run"
log DRYRUN "Dry run mode enabled. No changes will be pushed." "$dry_run"
log DRYRUN "Repository: $repository" "$dry_run"

REPO_DIR="/data/$(basename "$repository")"
REMOTE_URL="https://github.com/$repository"

# Configure git user/email
if [ -n "$gituser" ]; then
    git config --global user.name "$gituser"
fi
if [ -n "$gitmail" ]; then
    git config --global user.email "$gitmail"
fi
git config --global http.sslVerify false
git config --global credential.helper 'cache --timeout=7200'

# Clone or update repository
if [ ! -d "$REPO_DIR/.git" ]; then
    log DRYRUN "Cloning repository $repository..." "$dry_run"
    if ! git clone --depth=1 "$REMOTE_URL" "$REPO_DIR"; then
        log ERROR "Failed to clone repository $repository"
        exit 1
    fi
else
    log DRYRUN "Repository already exists, updating..." "$dry_run"
    cd "$REPO_DIR" || exit 1

    # Detect default branch dynamically
    DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')
    if [ -z "$DEFAULT_BRANCH" ]; then
        DEFAULT_BRANCH="main"
    fi

    # Fetch and reset hard to remote default branch
    git fetch origin "$DEFAULT_BRANCH" || { log ERROR "Git fetch failed"; exit 1; }
    git reset --hard "origin/$DEFAULT_BRANCH" || { log ERROR "Git reset failed"; exit 1; }
    git pull origin "$DEFAULT_BRANCH" || { log ERROR "Git pull failed"; exit 1; }
fi

cd "$REPO_DIR" || exit 1

# Iterate over all add-on folders with updater.json
for addon_dir in */; do
    [ -f "$addon_dir/updater.json" ] || continue

    SLUG="${addon_dir%/}"

    # Load updater.json properties
    upstream_repo=$(jq -r '.upstream_repo // empty' "$addon_dir/updater.json")
    github_beta=$(jq -r '.github_beta // false' "$addon_dir/updater.json")
    github_fulltag=$(jq -r '.github_fulltag // false' "$addon_dir/updater.json")
    github_havingasset=$(jq -r '.github_havingasset // false' "$addon_dir/updater.json")
    source=$(jq -r '.source // empty' "$addon_dir/updater.json")
    github_tagfilter=$(jq -r '.github_tagfilter // empty' "$addon_dir/updater.json")
    github_exclude=$(jq -r '.github_exclude // "zzzzzzzzzzzzzzzz"' "$addon_dir/updater.json")
    paused=$(jq -r '.paused // false' "$addon_dir/updater.json")
    dockerhub_by_date=$(jq -r '.dockerhub_by_date // false' "$addon_dir/updater.json")
    dockerhub_list_size=$(jq -r '.dockerhub_list_size // 100' "$addon_dir/updater.json")

    if [ "$paused" = true ]; then
        log INFO "$SLUG: Updates are paused, skipping." "$dry_run"
        continue
    fi

    # Get current upstream version
    current_version=$(jq -r '.upstream_version // empty' "$addon_dir/updater.json")
    if [ -z "$current_version" ]; then
        log WARN "$SLUG: No current upstream_version found, skipping." "$dry_run"
        continue
    fi

    last_version=""

    # Fetch latest version based on source
    if [ "$source" = "dockerhub" ]; then
        # Parse dockerhub repo and image
        repo_name="${upstream_repo%%/*}"
        image_name="${upstream_repo#*/}"

        filter_param=""
        if [ -n "$github_tagfilter" ] && [ "$github_tagfilter" != "null" ]; then
            filter_param="&name=$github_tagfilter"
        fi

        exclude_filter="$github_exclude"
        [ -z "$exclude_filter" ] && exclude_filter="zzzzzzzzzzzzzzzz"

        # Compose API URL
        url="https://hub.docker.com/v2/repositories/${repo_name}/${image_name}/tags?page_size=${dockerhub_list_size}${filter_param}"

        # Fetch tags and filter out undesired ones
        last_version=$(curl -fsSL "$url" \
            | jq -r '.results[].name' \
            | grep -vE "latest|dev|nightly|beta" \
            | grep -v "$exclude_filter" \
            | sort -V \
            | tail -n 1)

        # If beta enabled, pick dev tags
        if [ "$github_beta" = true ]; then
            last_version=$(curl -fsSL "$url" \
                | jq -r '.results[].name' \
                | grep "dev" \
                | grep -v "$exclude_filter" \
                | sort -V \
                | tail -n 1)
        fi

        # If by_date enabled, reorder by last_updated
        if [ "$dockerhub_by_date" = true ]; then
            url_date="https://hub.docker.com/v2/repositories/${repo_name}/${image_name}/tags/?page_size=${dockerhub_list_size}&ordering=last_updated${filter_param}"
            last_version=$(curl -fsSL "$url_date" \
                | jq -r '.results[].name' \
                | grep -vE "latest|dev|nightly" \
                | grep -v "$exclude_filter" \
                | sort -V \
                | tail -n 1)

            date=$(curl -fsSL "$url_date" \
                | jq -r --arg ver "$last_version" '.results[] | select(.name==$ver) | .last_updated' \
                | cut -d'T' -f1)

            last_version="${last_version}-${date}"
        fi

    else
        # For GitHub or other sources use lastversion tool (assumed installed)
        args="--at $source"

        [ "$github_fulltag" = true ] && args="$args --format tag"
        [ "$github_havingasset" = true ] && args="$args --having-asset"
        [ -n "$github_tagfilter" ] && [ "$github_tagfilter" != "null" ] && args="$args --only $github_tagfilter"
        [ -n "$github_exclude" ] && [ "$github_exclude" != "null" ] && args="$args --exclude $github_exclude"
        [ "$github_beta" = true ] && args="$args --pre"

        # Use lastversion to get latest tag
        last_version=$(lastversion "$upstream_repo" $args || true)

        # Fallback to GitHub packages if no releases
        if echo "$last_version" | grep -q "No release"; then
            packages=$(curl -fsSL "https://github.com/${upstream_repo}/packages" | grep -oP '/container/package/\K[^"]+')
            if [ -n "$packages" ]; then
                package="${packages%%$'\n'*}"
                last_version=$(curl -fsSL "https://github.com/${upstream_repo}/pkgs/container/${package}" \
                    | grep -oP 'tag=\K[^"]+' \
                    | grep -vE "latest|dev|nightly|beta" \
                    | sort -V | tail -n 1)
            fi
        fi
    fi

    if [ -z "$last_version" ]; then
        log WARN "$SLUG: No latest version found, skipping." "$dry_run"
        continue
    fi

    # Normalize versions for comparison
    current_cmp=${current_version//+/-}
    last_cmp=${last_version//+/-}

    if [ "$current_cmp" != "$last_cmp" ]; then
        log INFO "$SLUG: Update available: $current_version -> $last_version" "$dry_run"

        if [ "$dry_run" != true ]; then
            # Update version strings in files (config.json, build.json, updater.json)
            for file in config.json build.json updater.json; do
                path="$REPO_DIR/$SLUG/$file"
                if [ -f "$path" ]; then
                    # Replace current version with new version safely
                    tmpfile="${path}.tmp"
                    jq --arg ver "$last_version" '(.version // .upstream_version) |= $ver' "$path" > "$tmpfile" && mv "$tmpfile" "$path"
                fi
            done

            # Update changelog
            changelog="$REPO_DIR/$SLUG/CHANGELOG.md"
            date_str=$(date '+%Y-%m-%d')
            touch "$changelog"
            echo "" | cat - "$changelog" > "$changelog.tmp" && mv "$changelog.tmp" "$changelog" # blank line
            echo "## $last_version ($date_str)" | cat - "$changelog" > "$changelog.tmp" && mv "$changelog.tmp" "$changelog"
            if echo "$source" | grep -q "github"; then
                echo "- Updated from $upstream_repo (https://github.com/${upstream_repo}/releases)" | cat - "$changelog" > "$changelog.tmp" && mv "$changelog.tmp" "$changelog"
            else
                echo "- Updated from $upstream_repo" | cat - "$changelog" > "$changelog.tmp" && mv "$changelog.tmp" "$changelog"
            fi

            # Git commit and push
            cd "$REPO_DIR"
            git add -A
            git commit -m "Updater bot: $SLUG updated to $last_version" || true

            # Use token for push if dry_run false
            if [ "$dry_run" != true ]; then
                # Setup remote with token auth
                git remote set-url origin "https://${gituser}:${gitapi}@github.com/${repository}" 2>/dev/null || true
                git push origin "$DEFAULT_BRANCH" || log ERROR "$SLUG: Git push failed"
            else
                log DRYRUN "$SLUG: Dry run mode, skipping git push." "$dry_run"
            fi

            log INFO "$SLUG: Updated successfully to $last_version"
        else
            log DRYRUN "$SLUG: Dry run - would update to $last_version" "$dry_run"
        fi

    else
        log INFO "$SLUG: Up-to-date ($current_version)" "$dry_run"
    fi
done

log DRYRUN "===== ADDON UPDATER FINISHED =====" "$dry_run"

exit 0
