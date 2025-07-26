#!/bin/bash

set -e

CONFIG_PATH=/data/options.json
ADDONS_PATH=/addons
CHECK_TIME=$(jq -r '.check_time' $CONFIG_PATH)

log() {
    echo -e "\033[1;32m$1\033[0m"
}

warn() {
    echo -e "\033[1;33m$1\033[0m"
}

get_latest_docker_tag() {
    local image="$1"
    curl -s "https://hub.docker.com/v2/repositories/${image}/tags/?page_size=1&page=1&ordering=last_updated" | jq -r '.results[0].name'
}

run_check() {
    TIMESTAMP=$(date +"%d-%m-%Y %H:%M")
    log "🚀 HomeAssistant Addon Updater started at $TIMESTAMP"

    for addon_dir in "$ADDONS_PATH"/*/; do
        CONFIG_FILE="${addon_dir}config.json"
        UPDATER_JSON="${addon_dir}updater.json"

        if [[ ! -f "$CONFIG_FILE" ]]; then
            continue
        fi

        NAME=$(jq -r '.name' "$CONFIG_FILE")
        IMAGE=$(jq -r '.image // empty' "$CONFIG_FILE")

        if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
            warn "⚠️ Skipping $NAME — no Docker image"
            continue
        fi

        # Create updater.json if missing
        if [[ ! -f "$UPDATER_JSON" ]]; then
            NOW=$(date +"%d-%m-%Y %H:%M")
            echo "{\"last_update\": \"$NOW\"}" > "$UPDATER_JSON"
        fi

        CURRENT_VERSION=$(jq -r '.version' "$CONFIG_FILE")
        LATEST_VERSION=$(get_latest_docker_tag "$IMAGE")

        if [[ -z "$LATEST_VERSION" || "$LATEST_VERSION" == "null" ]]; then
            warn "⚠️ Could not get latest tag for $IMAGE"
            continue
        fi

        if [[ "$CURRENT_VERSION" != "$LATEST_VERSION" ]]; then
            jq --arg ver "$LATEST_VERSION" '.version = $ver' "$CONFIG_FILE" > "$CONFIG_FILE.tmp" && mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
            NOW=$(date +"%d-%m-%Y %H:%M")
            echo "{\"last_update\": \"$NOW\"}" > "$UPDATER_JSON"
            log "⬆️ Updated $NAME from $CURRENT_VERSION ➡️ $LATEST_VERSION"
        else
            log "✔ $NAME is already up-to-date ($CURRENT_VERSION)"
        fi
    done

    log "📅 Next check scheduled at $CHECK_TIME tomorrow"
}

run_check
