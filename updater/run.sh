#!/bin/bash

set -e

CONFIG_PATH=/data/options.json
ADDONS_PATH=/addons
CHECK_TIME=$(jq -r '.check_time' $CONFIG_PATH)
GOTIFY_URL=$(jq -r '.gotify_url' $CONFIG_PATH)
GOTIFY_TOKEN=$(jq -r '.gotify_token' $CONFIG_PATH)
MAILRISE_URL=$(jq -r '.mailrise_url' $CONFIG_PATH)

log() {
    echo -e "\033[1;32m$1\033[0m"
}

warn() {
    echo -e "\033[1;33m$1\033[0m"
}

send_notification() {
    MESSAGE="$1"
    if [[ -n "$GOTIFY_URL" && -n "$GOTIFY_TOKEN" ]]; then
        curl -s -X POST "$GOTIFY_URL/message" \
            -F "token=$GOTIFY_TOKEN" \
            -F "title=Addon Updater" \
            -F "message=$MESSAGE" \
            -F "priority=5" > /dev/null || warn "❌ Gotify notification failed"
    fi
    if [[ -n "$MAILRISE_URL" ]]; then
        curl -s -X POST "$MAILRISE_URL" \
            -H "Content-Type: application/json" \
            -d "{\"message\": \"$MESSAGE\"}" > /dev/null || warn "❌ Mailrise notification failed"
    fi
}

get_latest_docker_tag() {
    local image="$1"
    local latest_tag=""
    for ((i=0; i<5; i++)); do
        latest_tag=$(curl -s "https://hub.docker.com/v2/repositories/${image}/tags/?page_size=1&page=1&ordering=last_updated" | jq -r '.results[0].name' || echo "")
        if [[ -n "$latest_tag" && "$latest_tag" != "null" ]]; then
            echo "$latest_tag"
            return
        fi
        warn "Retrying to fetch tag for $image (attempt $((i+1)))..."
        sleep 2
    done
    echo ""
}

get_rate_limit() {
    # Fetch DockerHub rate limit headers via HEAD request
    local headers
    headers=$(curl -sI "https://hub.docker.com/v2/repositories/library/alpine/tags/?page_size=1")
    local limit remaining reset

    limit=$(echo "$headers" | grep -i '^RateLimit-Limit:' | awk '{print $2}' | tr -d $'\r')
    remaining=$(echo "$headers" | grep -i '^RateLimit-Remaining:' | awk '{print $2}' | tr -d $'\r')
    reset_epoch=$(echo "$headers" | grep -i '^RateLimit-Reset:' | awk '{print $2}' | tr -d $'\r')

    if [[ -z "$limit" || -z "$remaining" || -z "$reset_epoch" ]]; then
        echo "Rate limit info: unknown"
        return
    fi

    local reset_time
    reset_time=$(date -d "@$reset_epoch" +"%H:%M:%S")

    echo "DockerHub API rate limit: $remaining / $limit remaining, resets at $reset_time"
}

run_check() {
    TIMESTAMP=$(date +"%d-%m-%Y %H:%M")
    log "🚀 HomeAssistant Addon Updater started at $TIMESTAMP"

    ADDONS=$(ls -1 $ADDONS_PATH)
    for addon in $ADDONS; do
        CONFIG_FILE="$ADDONS_PATH/$addon/config.json"
        if [[ ! -f "$CONFIG_FILE" ]]; then continue; fi

        NAME=$(jq -r '.name' "$CONFIG_FILE")
        IMAGE=$(jq -r '.image // empty' "$CONFIG_FILE")

        if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
            warn "⚠️ Skipping $NAME — no Docker image"
            continue
        fi

        UPDATER_JSON="$ADDONS_PATH/$addon/updater.json"
        if [[ ! -f "$UPDATER_JSON" ]]; then
            NOW=$(date +"%d-%m-%Y %H:%M")
            echo "{\"last_update\": \"$NOW\"}" > "$UPDATER_JSON"
        fi

        CURRENT_VERSION=$(jq -r '.version' "$CONFIG_FILE")
        LATEST_VERSION=$(get_latest_docker_tag "$IMAGE")

        if [[ -z "$LATEST_VERSION" ]]; then
            warn "⚠️ Could not get latest tag for $IMAGE"
            continue
        fi

        if [[ "$CURRENT_VERSION" != "$LATEST_VERSION" ]]; then
            jq --arg ver "$LATEST_VERSION" '.version = $ver' "$CONFIG_FILE" > "$CONFIG_FILE.tmp" && mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
            NOW=$(date +"%d-%m-%Y %H:%M")
            echo "{\"last_update\": \"$NOW\"}" > "$UPDATER_JSON"
            log "⬆️ Updated $NAME from $CURRENT_VERSION ➡️ $LATEST_VERSION"
            send_notification "Updated $NAME to version $LATEST_VERSION"
        else
            log "✔ $NAME is already up-to-date ($CURRENT_VERSION)"
        fi
    done

    RATE_LIMIT_INFO=$(get_rate_limit)
    log "$RATE_LIMIT_INFO"

    log "📅 Next check scheduled at $CHECK_TIME tomorrow"
}

first_run=true

while true; do
    NOW=$(date +%H:%M)

    if $first_run; then
        run_check
        first_run=false
    elif [[ "$NOW" == "$CHECK_TIME" ]]; then
        run_check
        sleep 60  # avoid multiple runs in the same minute
    fi

    sleep 30
done
