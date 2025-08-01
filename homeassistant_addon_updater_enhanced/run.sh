#!/usr/bin/with-contenv bashio
set -e

# =====================
# MAIN SCRIPT
# =====================

# Load configuration values
GOTIFY_URL=$(bashio::config 'gotify_url')
GOTIFY_TOKEN=$(bashio::config 'gotify_token')
CHECK_INTERVAL=$(bashio::config 'check_interval')

# Log startup message
bashio::log.info "Starting Addon Updater Enhanced"
bashio::log.debug "Check interval: ${CHECK_INTERVAL} seconds"

# Function to send Gotify notification
send_notification() {
    local title=$1
    local message=$2
    local priority=${3:-5}

    if [[ -z "$GOTIFY_URL" || -z "$GOTIFY_TOKEN" ]]; then
        bashio::log.debug "Gotify not configured, skipping notification"
        return
    fi

    curl -sS -X POST "${GOTIFY_URL}/message?token=${GOTIFY_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"${title}\", \"message\":\"${message}\", \"priority\":${priority}}" \
        --connect-timeout 10 || bashio::log.warning "Failed to send Gotify notification"
}

# Main update check function
check_updates() {
    local updates=()
    local no_updates=()
    
    # Get installed addons
    ADDONS=$(ha addons --raw-json)
    
    # Check each addon
    for addon in $(echo "${ADDONS}" | jq -c '.data.addons[]'); do
        slug=$(echo "${addon}" | jq -r '.slug')
        name=$(echo "${addon}" | jq -r '.name')
        version=$(echo "${addon}" | jq -r '.version')
        available=$(echo "${addon}" | jq -r '.available_version')
        
        if [[ "$version" != "$available" ]] && [[ "$available" != "null" ]]; then
            updates+=("${name}: ${version} → ${available}")
        else
            no_updates+=("${name}")
        fi
    done
    
    # Generate report
    local message="⚡ Addon Update Report ⚡\n"
    message+="📅 $(date +'%Y-%m-%d %H:%M:%S')\n\n"
    
    if [[ ${#updates[@]} -gt 0 ]]; then
        message+="🔄 Updates Available (${#updates[@]}):\n"
        for update in "${updates[@]}"; do
            message+="- ${update}\n"
        done
        message+="\n"
    else
        message+="✅ All addons are up to date\n\n"
    fi
    
    message+="📋 No updates needed for (${#no_updates[@]}):\n"
    for item in "${no_updates[@]}"; do
        message+="- ${item}\n"
    done
    
    # Send notification
    send_notification "Addon Update Report" "${message}" $([[ ${#updates[@]} -gt 0 ]] && echo 8 || echo 5)
}

# Main loop
bashio::log.info "Starting update monitoring"
while true; do
    check_updates
    bashio::log.debug "Sleeping for ${CHECK_INTERVAL} seconds"
    sleep "${CHECK_INTERVAL}"
done
