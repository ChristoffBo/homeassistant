#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

##########
# UPDATE #
##########

bashio::log.info "Starting $(lastversion --version)"

if bashio::config.true "dry_run"; then
    bashio::log.warning "Dry run mode : on"
fi

bashio::log.info "Checking status of referenced repositories..."
VERBOSE=$(bashio::config 'verbose')

# Git configuration
GITUSER=$(bashio::config 'gituser')
GITMAIL=$(bashio::config 'gitmail')
GITAPI=$(bashio::config 'gitapi')
REPOSITORY=$(bashio::config 'repository')
NOTIFY_ENABLED=$(bashio::config.true "notify") || true

git config --system http.sslVerify false
git config --system credential.helper 'cache --timeout 7200'
git config --system user.name "${GITUSER}"
if [[ "$GITMAIL" != "null" && -n "$GITMAIL" ]]; then
    git config --system user.email "${GITMAIL}"
fi

if [ -n "$GITAPI" ] && [ "$GITAPI" != "null" ]; then
    export GITHUB_API_TOKEN="$GITAPI"
fi

BASENAME=$(basename "https://github.com/$REPOSITORY")

# Clone or update repository
if [ ! -d "/data/$BASENAME" ]; then
    [ "$VERBOSE" = true ] && bashio::log.info "... cloning ${REPOSITORY}"
    cd /data/ || exit
    git clone "https://github.com/${REPOSITORY}"
else
    [ "$VERBOSE" = true ] && bashio::log.info "... updating ${REPOSITORY}"
    cd "/data/$BASENAME" || exit
    DEFAULT_BRANCH=$(git remote show origin | sed -n '/HEAD branch/s/.*: //p')
    git pull --rebase origin > /dev/null || git reset --hard "origin/${DEFAULT_BRANCH}" > /dev/null
    git pull --rebase origin > /dev/null || (rm -r "/data/$BASENAME" && git clone "https://github.com/${REPOSITORY}")
fi

cd "/data/$BASENAME" || exit

# Prepare summary arrays
UPDATED=()
NOT_UPDATED=()

# Iterate through all addon folders that contain updater.json
for f in */; do
    ADDON_PATH="/data/$BASENAME/$f"
    if [ -f "$ADDON_PATH/updater.json" ]; then
        SLUG=${f//\//}

        # Pull latest changes for this addon folder
        cd "/data/$BASENAME" || exit
        git pull --rebase &> /dev/null || git reset --hard &> /dev/null
        git pull --rebase &> /dev/null

        cd "$ADDON_PATH" || {
            bashio::log.error "$SLUG addon folder not found. Skipping."
            continue
        }

        # Extract variables from updater.json
        UPSTREAM=$(jq -r '.upstream_repo // empty' updater.json)
        BETA=$(jq -r '.github_beta // false' updater.json)
        FULLTAG=$(jq -r '.github_fulltag // false' updater.json)
        HAVINGASSET=$(jq -r '.github_havingasset // false' updater.json)
        SOURCE=$(jq -r '.source // empty' updater.json)
        FILTER_TEXT=$(jq -r '.github_tagfilter // empty' updater.json)
        EXCLUDE_TEXT=$(jq -r '.github_exclude // "zzzzzzzzzzzzzzzz"' updater.json)
        PAUSED=$(jq -r '.paused // false' updater.json)
        BYDATE=$(jq -r '.dockerhub_by_date // false' updater.json)
        LISTSIZE=$(jq -r '.dockerhub_list_size // 100' updater.json)
        DATE=$(date '+%d-%m-%Y')

        # Skip if paused
        if [ "$PAUSED" = true ]; then
            bashio::log.warning "... $SLUG addon updates are paused, skipping"
            NOT_UPDATED+=("$SLUG (paused)")
            continue
        fi

        # Current upstream version from updater.json
        CURRENT=$(jq -r '.upstream_version // empty' updater.json)
        if [ -z "$CURRENT" ]; then
            bashio::log.error "$SLUG has no upstream_version in updater.json, skipping."
            NOT_UPDATED+=("$SLUG (no upstream_version)")
            continue
        fi

        # Prepare to find last version depending on source
        LASTVERSION=""
        set_continue=false

        if [ "$SOURCE" = "dockerhub" ]; then
            # Dockerhub source
            DOCKERHUB_REPO="${UPSTREAM%%/*}"
            DOCKERHUB_IMAGE=$(echo "$UPSTREAM" | cut -d "/" -f2)

            # Build filter string
            if [ -z "$FILTER_TEXT" ] || [ "$FILTER_TEXT" = "null" ]; then
                FILTER_TEXT=""
            else
                [ "$VERBOSE" = true ] && bashio::log.info "... $SLUG : filter_text is on"
                FILTER_TEXT="&name=$FILTER_TEXT"
            fi

            if [ -z "$EXCLUDE_TEXT" ] || [ "$EXCLUDE_TEXT" = "null" ]; then
                EXCLUDE_TEXT="zzzzzzzzzzzzzzzzzz"
            fi

            LASTVERSION=$(
                curl -f -s "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=${LISTSIZE}${FILTER_TEXT}" \
                    | jq -r '.results[] | .name' \
                    | grep -v -E "latest|dev|nightly|beta" \
                    | grep -v "$EXCLUDE_TEXT" \
                    | sort -V | tail -n1
            )

            if [ "$BETA" = true ]; then
                LASTVERSION=$(
                    curl -f -s "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=${LISTSIZE}${FILTER_TEXT}" \
                        | jq -r '.results[] | .name' \
                        | grep -E "dev" \
                        | grep -v "$EXCLUDE_TEXT" \
                        | sort -V | tail -n1
                )
            fi

            if [ "$BYDATE" = true ]; then
                LASTVERSION=$(
                    curl -f -s "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=${LISTSIZE}&ordering=last_updated${FILTER_TEXT}" \
                        | jq -r '.results[] | .name' \
                        | grep -v -E "latest|dev|nightly" \
                        | grep -v "$EXCLUDE_TEXT" \
                        | sort -V | tail -n1
                )
                DATE=$(
                    curl -f -s "https://hub.docker.com/v2/repositories/${DOCKERHUB_REPO}/${DOCKERHUB_IMAGE}/tags?page_size=${LISTSIZE}&ordering=last_updated${FILTER_TEXT}" \
                        | jq -r --arg LASTVERSION "$LASTVERSION" '.results[] | select(.name == $LASTVERSION) | .last_updated' \
                        | cut -d'T' -f1
                )
                LASTVERSION="${LASTVERSION}-${DATE}"
            fi

            [ "$VERBOSE" = true ] && bashio::log.info "... $SLUG : lastversion detected as $LASTVERSION"

        else
            # Other source (github, gitlab, etc.)

            # Only pass --at if SOURCE is valid and not null or empty
            LASTVERSION=""
            if [[ "$SOURCE" != "null" && -n "$SOURCE" ]]; then
                ARGS="--at $SOURCE"
            else
                ARGS=""
            fi

            # Other flags
            if [ "$FULLTAG" = true ]; then
                ARGS="$ARGS --format tag"
            fi

            if [ "$HAVINGASSET" = true ]; then
                ARGS="$ARGS --having-asset"
            fi

            if [[ -n "$FILTER_TEXT" && "$FILTER_TEXT" != "null" ]]; then
                ARGS="$ARGS --only $FILTER_TEXT"
            fi

            if [[ -n "$EXCLUDE_TEXT" && "$EXCLUDE_TEXT" != "null" ]]; then
                ARGS="$ARGS --exclude $EXCLUDE_TEXT"
            fi

            if [ "$BETA" = true ]; then
                ARGS="$ARGS --pre"
            fi

            # Use lastversion command with ARGS
            LASTVERSION=$(lastversion $ARGS "$UPSTREAM" 2>/tmp/lastversion_error.log) || {
                # Check if error is about no release found on GitHub (fallback to packages)
                if grep -q "No release" /tmp/lastversion_error.log; then
                    bashio::log.warning "$SLUG: No release found, checking packages..."
                    last_packages="$(curl -s -L https://github.com/"$UPSTREAM"/packages | sed -n "s/.*\/container\/package\/\([^\"]*\).*/\1/p")" || true
                    last_package="$(echo "$last_packages" | head -n 1)" || true
                    if [[ "$(echo -n "$last_packages" | grep -c '^')" -gt 0 ]]; then
                        bashio::log.warning "$SLUG: Found packages, using $last_package"
                        LASTVERSION="$(curl -s -L https://github.com/"$UPSTREAM"/pkgs/container/"$last_package" | sed -n "s/.*?tag=\([^\"]*\)\">.*/\1/p" | grep -v latest | sort -V | tail -n 1)" || true
                        if [[ -z "$LASTVERSION" ]]; then
                            bashio::log.warning "$SLUG: No packages found"
                            set_continue=true
                        fi
                    else
                        set_continue=true
                    fi
                else
                    set_continue=true
                fi
            }
            rm -f /tmp/lastversion_error.log
            if [ "${set_continue:-false}" = true ]; then
                NOT_UPDATED+=("$SLUG (no valid version found)")
                continue
            fi
        fi

        # Sanitize quotes from versions
        LASTVERSION=${LASTVERSION//\"/}
        CURRENT=${CURRENT//\"/}

        # Compare and update if needed
        if [ "$CURRENT" != "$LASTVERSION" ]; then
            bashio::log.info "... $SLUG : update from $CURRENT to $LASTVERSION"

            # Update version in all relevant files: updater.json, config.json, build.json
            for file in updater.json config.json build.json; do
                FILEPATH="$ADDON_PATH/$file"
                if [ -f "$FILEPATH" ]; then
                    jq --arg v "$LASTVERSION" 'if has("version") then .version = $v elif has("upstream_version") then .upstream_version = $v else . end' "$FILEPATH" | sponge "$FILEPATH"
                    # Special handling for updater.json last_update date
                    if [ "$file" = "updater.json" ]; then
                        jq --arg d "$DATE" '.last_update = $d' "$FILEPATH" | sponge "$FILEPATH"
                    fi
                fi
            done

            # Also update "version" field in config.yaml if exists
            if [ -f "$ADDON_PATH/config.yaml" ]; then
                sed -i "s/^version:.*/version: \"$LASTVERSION\"/" "$ADDON_PATH/config.yaml"
            fi

            # Update version strings in other common files if present (Dockerfile, build.yaml)
            for otherfile in Dockerfile build.yaml; do
                if [ -f "$ADDON_PATH/$otherfile" ]; then
                    sed -i "s/$CURRENT/$LASTVERSION/g" "$ADDON_PATH/$otherfile"
                fi
            done

            # Update CHANGELOG.md
            CHANGELOG="$ADDON_PATH/CHANGELOG.md"
            if [ ! -f "$CHANGELOG" ]; then
                touch "$CHANGELOG"
            fi
            if [[ "$SOURCE" == *github* ]]; then
                sed -i "1i - Update to latest version from $UPSTREAM (changelog: https://github.com/${UPSTREAM%/}/releases)" "$CHANGELOG"
            else
                sed -i "1i - Update to latest version from $UPSTREAM" "$CHANGELOG"
            fi
            sed -i "1i ## $LASTVERSION ($DATE)" "$CHANGELOG"
            sed -i "1i " "$CHANGELOG"

            bashio::log.info "... $SLUG : files updated"

            # Git commit and push if not dry run
            git add -A
            git commit -m "Updater bot : $SLUG updated to $LASTVERSION" > /dev/null || true

            git remote set-url origin "https://${GITUSER}:${GITHUB_API_TOKEN}@github.com/${REPOSITORY}" &> /dev/null

            if ! bashio::config.true "dry_run"; then
                git push &> /dev/null || bashio::log.error "Failed to push updates for $SLUG"
            fi

            UPDATED+=("$SLUG: $CURRENT → $LASTVERSION")
        else
            bashio::log.info "... $SLUG is up-to-date ($CURRENT)"
            NOT_UPDATED+=("$SLUG: $CURRENT")
        fi
    fi
done

# Compose Gotify notification message if enabled
if [ "$NOTIFY_ENABLED" = true ]; then
    MSG="Add-ons Update Report:\n\n"

    if [ ${#UPDATED[@]} -gt 0 ]; then
        MSG+="🟢 Updated add-ons:\n"
        for u in "${UPDATED[@]}"; do
            MSG+="- $u\n"
        done
    else
        MSG+="🟡 No add-ons were updated.\n"
    fi

    if [ ${#NOT_UPDATED[@]} -gt 0 ]; then
        MSG+="\n🔵 Add-ons already up-to-date or skipped:\n"
        for n in "${NOT_UPDATED[@]}"; do
            MSG+="- $n\n"
        done
    fi

    # Send notification via Gotify
    GOTIFY_URL=$(bashio::config 'gotify_url' || echo "")
    GOTIFY_TOKEN=$(bashio::config 'gotify_token' || echo "")
    GOTIFY_TITLE="Repository Updater Report"

    if [ -n "$GOTIFY_URL" ] && [ -n "$GOTIFY_TOKEN" ]; then
        curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \
             -H "Content-Type: application/json" \
             -d "{\"title\":\"$GOTIFY_TITLE\",\"message\":\"$MSG\",\"priority\":5}" > /dev/null
        bashio::log.info "Notification sent via Gotify."
    else
        bashio::log.warning "Gotify URL or token not set; skipping notification."
    fi
else
    bashio::log.info "Notifications disabled by configuration."
fi

# Clean dry run files if dry_run is true
if bashio::config.true "dry_run"; then
    rm -rf /data/*
fi

bashio::log.info "Addons update completed"
