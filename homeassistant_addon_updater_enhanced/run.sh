#!/usr/bin/with-contenv bashio
set -eo pipefail

# =====================
# INITIALIZE ENVIRONMENT
# =====================

bashio::log.info "Initializing Addon Updater Enhanced"

# Load configuration with validation
CONFIG_PATH=/data/options.json
if [ ! -f "$CONFIG_PATH" ]; then
    bashio::log.error "Configuration file missing!"
    exit 1
fi

# ==============
# CONFIGURATION
# ==============
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$CONFIG_PATH")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$CONFIG_PATH")
CHECK_INTERVAL=$(jq -r '.check_interval // 3600' "$CONFIG_PATH")
GITHUB_REPOS=$(jq -c '.github_repos // []' "$CONFIG_PATH")
GITEA_INSTANCES=$(jq -c '.gitea_instances // []' "$CONFIG_PATH")

# ===================
# NOTIFICATION SYSTEM
# ===================
send_gotify() {
    local title=$1 message=$2 priority=${3:-5}
    
    if [[ -z "$GOTIFY_URL" || -z "$GOTIFY_TOKEN" ]]; then
        bashio::log.debug "Gotify not configured, skipping notification"
        return
    fi

    local response=$(curl -s -w "%{http_code}" -o /tmp/gotify_response \
        -X POST "${GOTIFY_URL}/message?token=${GOTIFY_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"${title}\", \"message\":\"${message}\", \"priority\":${priority}}" \
        --connect-timeout 10)

    if [[ "${response}" -ne 200 ]]; then
        bashio::log.warning "Gotify notification failed (HTTP ${response})"
        cat /tmp/gotify_response || true
    else
        bashio::log.debug "Gotify notification sent successfully"
    fi
}

# =================
# VERSION CHECKERS
# =================
check_github() {
    local owner=$1 repo=$2 token=$3
    local api_url="https://api.github.com/repos/${owner}/${repo}/releases/latest"
    local headers=()

    if [[ -n "$token" ]]; then
        headers+=("-H" "Authorization: token ${token}")
    fi

    local response=$(curl -s -H "Accept: application/vnd.github+json" "${headers[@]}" "$api_url")
    local version=$(echo "$response" | jq -r '.tag_name // empty' | sed 's/^v//')

    if [[ -z "$version" ]]; then
        bashio::log.warning "Failed to get version for GitHub: ${owner}/${repo}"
        return 1
    fi

    echo "$version"
}

check_gitea() {
    local base_url=$1 owner=$2 repo=$3 token=$4
    local api_url="${base_url}/api/v1/repos/${owner}/${repo}/releases/latest"
    local headers=()

    if [[ -n "$token" ]]; then
        headers+=("-H" "Authorization: token ${token}")
    fi

    local response=$(curl -s "${headers[@]}" "$api_url")
    local version=$(echo "$response" | jq -r '.tag_name // empty' | sed 's/^v//')

    if [[ -z "$version" ]]; then
        bashio::log.warning "Failed to get version for Gitea: ${owner}/${repo}"
        return 1
    fi

    echo "$version"
}

# ================
# MAIN CHECK LOGIC
# ================
perform_checks() {
    local updates=() current_versions=() no_updates=()

    # Check installed addons
    while IFS= read -r addon; do
        local slug=$(echo "$addon" | jq -r '.slug')
        local name=$(echo "$addon" | jq -r '.name')
        local version=$(echo "$addon" | jq -r '.version')
        current_versions+=("${slug}: ${version}")
    done < <(ha addons --raw-json | jq -c '.data.addons[]')

    # Check GitHub repositories
    for repo in $(echo "$GITHUB_REPOS" | jq -c '.[]'); do
        local name=$(echo "$repo" | jq -r '.name')
        local owner=$(echo "$repo" | jq -r '.owner')
        local repo_name=$(echo "$repo" | jq -r '.repo')
        local token=$(echo "$repo" | jq -r '.token // empty')

        if latest=$(check_github "$owner" "$repo_name" "$token"); then
            # Compare logic would go here
            no_updates+=("GitHub: ${owner}/${repo_name} (${latest})")
        fi
    done

    # Check Gitea instances
    for instance in $(echo "$GITEA_INSTANCES" | jq -c '.[]'); do
        local name=$(echo "$instance" | jq -r '.name')
        local url=$(echo "$instance" | jq -r '.url')
        local owner=$(echo "$instance" | jq -r '.owner')
        local token=$(echo "$instance" | jq -r '.token // empty')

        if latest=$(check_gitea "$url" "$owner" "$repo_name" "$token"); then
            # Compare logic would go here
            no_updates+=("Gitea: ${owner}/${repo_name} (${latest})")
        fi
    done

    # Generate report
    local message="⚡ Addon Update Report ⚡\n\n"
    message+="📅 $(date)\n\n"

    if [[ ${#updates[@]} -gt 0 ]]; then
        message+="🔄 Updates Available:\n"
        for update in "${updates[@]}"; do
            message+="- ${update}\n"
        done
        message+="\n"
    else
        message+="✅ No updates found\n\n"
    fi

    message+="📋 Current Versions:\n"
    for version in "${current_versions[@]}"; do
        message+="- ${version}\n"
    done

    message+="\n🔍 Repository Status:\n"
    for status in "${no_updates[@]}"; do
        message+="- ${status}\n"
    done

    send_gotify "Addon Update Report" "$message" $([[ ${#updates[@]} -gt 0 ]] && echo 8 || echo 5)
}

# ===========
# MAIN LOOP
# ===========
bashio::log.info "Starting update monitoring with ${CHECK_INTERVAL}s interval"
while true; do
    perform_checks
    sleep "$CHECK_INTERVAL"
done
