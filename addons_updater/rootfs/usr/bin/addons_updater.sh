#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

##########
# UPDATE #
##########

# New Gotify notification function
send_gotify() {
    local message="$1"
    if bashio::config.true 'enable_notifications'; then
        gotify_url=$(bashio::config 'gotify_url')
        gotify_token=$(bashio::config 'gotify_token')
        
        if [ -n "$gotify_url" ] && [ -n "$gotify_token" ]; then
            curl -s -X POST "${gotify_url}/message?token=${gotify_token}" \
                -F "title=Addons Updater" \
                -F "message=${message}" \
                -F "priority=5" \
                --insecure > /dev/null
            bashio::log.info "Sent Gotify notification"
        fi
    fi
}

# Send start notification
send_gotify "Addon update process started"

bashio::log.info "Starting $(lastversion --version)"

if bashio::config.true "dry_run"; then
    bashio::log.warning "Dry run mode : on"
fi

bashio::log.info "Checking status of referenced repositoriess..."
VERBOSE=$(bashio::config 'verbose')

#Defining github value
LOGINFO="... github authentification" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi

GITUSER=$(bashio::config 'gituser')
GITMAIL=$(bashio::config 'gitmail')
git config --system http.sslVerify false
git config --system credential.helper 'cache --timeout 7200'
git config --system user.name "${GITUSER}"
if [[ "$GITMAIL" != "null" ]]; then git config --system user.email "${GITMAIL}"; fi

if bashio::config.has_value 'gitapi'; then
    LOGINFO="... setting github API" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi
    GITHUB_API_TOKEN=$(bashio::config 'gitapi')
    export GITHUB_API_TOKEN
fi

#Create or update local version
REPOSITORY=$(bashio::config 'repository')
BASENAME=$(basename "https://github.com/$REPOSITORY")

if [ ! -d "/data/$BASENAME" ]; then
    LOGINFO="... cloning ${REPOSITORY}" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi
    cd /data/ || exit
    git clone "https://github.com/${REPOSITORY}"
else
    LOGINFO="... updating ${REPOSITORY}" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi
    cd "/data/$BASENAME" || exit
    git pull --rebase origin > /dev/null || git reset --hard origin/master > /dev/null
    git pull --rebase origin > /dev/null || (rm -r "/data/$BASENAME" && git clone "https://github.com/${REPOSITORY}")
fi

LOGINFO="... parse addons" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi

# Go through all folders, add to filters if not existing

cd /data/"$BASENAME" || exit
for f in */; do

    if [ -f /data/"$BASENAME"/"$f"/updater.json ]; then
        SLUG=${f//\//}

        # Rebase
        LOGINFO="... updating ${REPOSITORY}" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi
        cd "/data/$BASENAME" || exit
        git pull --rebase &> /dev/null || git reset --hard &> /dev/null
        git pull --rebase &> /dev/null

        #Define the folder addon
        LOGINFO="... $SLUG : checking slug exists in repo" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi
        cd /data/"${BASENAME}"/"${SLUG}" || {
            bashio::log.error "$SLUG addon not found in this repository. Exiting."
            continue
        }

        # Get variables
        UPSTREAM=$(jq -r .upstream_repo updater.json)
        BETA=$(jq -r .github_beta updater.json)
        FULLTAG=$(jq -r .github_fulltag updater.json)
        HAVINGASSET=$(jq -r .github_havingasset updater.json)
        SOURCE=$(jq -r .source updater.json)
        FILTER_TEXT=$(jq -r .github_tagfilter updater.json)
        EXCLUDE_TEXT=$(jq -r .github_exclude updater.json)
        EXCLUDE_TEXT="${EXCLUDE_TEXT:-zzzzzzzzzzzzzzzz}"
        PAUSED=$(jq -r .paused updater.json)
        DATE="$(date '+%d-%m-%Y')"
        BYDATE=$(jq -r .dockerhub_by_date updater.json)

        # Number of elements to check in dockerhub
        if grep -q "dockerhub_list_size" updater.json; then
            LISTSIZE=$(jq -r .dockerhub_list_size updater.json)
        else
            LISTSIZE=100
        fi

        #Skip if paused
        if [[ "$PAUSED" = true ]]; then
            bashio::log.magenta "... $SLUG addon updates are paused, skipping"
            continue
        fi

        #Find current version
        LOGINFO="... $SLUG : get current version" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi
        CURRENT=$(jq .upstream_version updater.json) \
            || {
                bashio::log.error "$SLUG addon upstream tag not found in updater.json. Exiting."
                continue
            }

        # ================== GITEA SUPPORT ADDITION ==================
        if [[ "$SOURCE" = gitea ]]; then
            LOGINFO="... $SLUG : source is gitea" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi
            GITEA_API_URL=$(bashio::config 'gitea_api_url')
            GITEA_TOKEN=$(bashio::config 'gitea_token')
            
            # Get latest release
            api_url="${GITEA_API_URL}/repos/${UPSTREAM}/releases/latest"
            release=$(curl -s -H "Authorization: token ${GITEA_TOKEN}" \
                -H "Accept: application/json" "${api_url}")
            LASTVERSION=$(echo "$release" | jq -r .tag_name)
            
            # Add brackets
            LASTVERSION='"'${LASTVERSION}'"'
        # ================== END GITEA ADDITION ==================
        
        elif [[ "$SOURCE" = dockerhub ]]; then
            # ... [ORIGINAL DOCKERHUB CODE UNCHANGED] ...
        else
            # ... [ORIGINAL GITHUB CODE UNCHANGED] ...
        fi

        # Avoid characters incompatible with HomeAssistant version name
        LASTVERSION2=${LASTVERSION//+/-}
        CURRENT2=${CURRENT//+/-}

        # Update if needed
        if [ "${CURRENT2}" != "${LASTVERSION2}" ]; then
            LOGINFO="... $SLUG : update from ${CURRENT} to ${LASTVERSION}" && if [ "$VERBOSE" = true ]; then bashio::log.info "$LOGINFO"; fi

            # ... [ORIGINAL UPDATE CODE UNCHANGED] ...

            # GOTIFY NOTIFICATION
            if bashio::config.true 'enable_notifications'; then
                send_gotify "Updated $SLUG from ${CURRENT} to ${LASTVERSION}"
            fi
        else
            bashio::log.green "... $SLUG is up-to-date ${CURRENT}"
        fi
    fi
done || true # Continue even if issue

# Clean dry run
if bashio::config.true "dry_run"; then
    rm -r /data/*
fi

# FINAL GOTIFY NOTIFICATION
send_gotify "Addons update completed"
bashio::log.info "Addons update completed"
