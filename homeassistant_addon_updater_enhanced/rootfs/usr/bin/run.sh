#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -eo pipefail

# =====================
# MAIN SCRIPT
# =====================

# Import libraries
source /usr/lib/bashio/modules/logging.sh

# Load configuration
CONFIG_PATH=/data/options.json
if [ ! -f "$CONFIG_PATH" ]; then
    bashio::log.error "Configuration file missing!"
    exit 1
fi

# Parse configuration
GOTIFY_URL=$(jq -r '.gotify_url // empty' "$CONFIG_PATH")
GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$CONFIG_PATH")
CHECK_INTERVAL=$(jq -r '.check_interval // 3600' "$CONFIG_PATH")
GITHUB_REPOS=$(jq -c '.github_repos // []' "$CONFIG_PATH")
GITEA_INSTANCES=$(jq -c '.gitea_instances // []' "$CONFIG_PATH")
VERBOSE=$(jq -r '.verbose_logging // false' "$CONFIG_PATH")

# Set log level
if [ "$VERBOSE" = "true" ]; then
    bashio::log.level "debug"
    bashio::log.debug "Verbose logging enabled"
fi

# ===================
# NOTIFICATION SYSTEM
# ===================
send_gotify() {
    local title=$1 message=$2 priority=${3:-5}
    
    if [[ -z "$GOTIFY_URL" || -z "$GOTIFY_TOKEN" ]]; then
        bashio::log.debug "Gotify not configured, skipping notification"
        return 0
    fi

    local response status
    response=$(curl -sS -w "%{http_code}" -o /tmp/gotify_response \
        -X POST "${GOTIFY_URL}/message?token=${GOTIFY_TOKEN}" \
        -H "Content-Type: application/json" \
        -d @- <<EOF
{
    "title": "${title}",
    "message": "${message}",
    "priority": ${priority}
}
EOF
    ) || {
        bashio::log.warning "Gotify connection failed"
        return 1
    }

    status=${response: -3}
    if [[ "$status" -ne 200 ]]; then
        bashio::log.warning "Gotify notification failed (HTTP ${status})"
        [ -f /tmp/gotify_response ] && bashio::log.debug "$(cat /tmp/gotify_response)"
        return 1
    fi

    bashio::log.debug "Gotify notification sent successfully"
    return 0
}

# =================
# VERSION CHECKERS
# =================
check_github_release() {
    local owner=$1 repo=$2 token=$3
    local api_url="https://api.github.com/repos/${owner}/${repo}/releases/latest"
    local headers=()
    
    if [[ -n "$token" ]]; then
        headers+=("-H" "Authorization: Bearer ${token}")
    fi
    
    local response
    response=$(curl -sS "${headers[@]}" "$api_url") || {
        bashio::log.warning "GitHub API request failed"
        return 1
    }
    
    local version
    version=$(echo "$response" | jq -r '.tag_name // empty' | sed 's/^v//')
    
    if [[ -z "$version" ]]; then
        bashio::log.warning "No version found for GitHub: ${owner}/${repo}"
        return 1
    fi
    
    echo "$version"
}

check_gitea_release() {
    local base_url=$1 owner=$2 repo=$3 token=$4 verify_ssl=$5
    local api_url="${base_url}/api/v1/repos/${owner}/${repo}/releases/latest"
    local headers=() curl_opts=()
    
    if [[ -n "$token" ]]; then
        headers+=("-H" "Authorization: token ${token}")
    fi
    
    if [[ "$verify_ssl" == "false" ]]; then
        curl_opts+=("-k")
    fi
    
    local response
    response=$(curl -sS "${curl_opts[@]}" "${headers[@]}" "$api_url") || {
        bashio::log.warning "Gitea API request failed"
        return 1
    }
    
    local version
    version=$(echo "$response" | jq -r '.tag_name // empty' | sed 's/^v//')
    
    if [[ -z "$version" ]]; then
        bashio::log.warning "No version found for Gitea: ${owner}/${repo}"
        return 1
    fi
    
    echo "$version"
}

# =====================
# VERSION COMPARISON
# =====================
version_gt() { 
    test "$(printf '%s\n' "$@" | sort -V | head -n 1)" != "$1"; 
}

# ================
# MAIN CHECK LOGIC
# ================
perform_checks() {
    local updates=()
    declare -A current_versions
    declare -A latest_versions
    local no_updates=()
    
    # Get installed addon versions
    while IFS= read -r addon; do
        local slug name version
        slug=$(echo "$addon" | jq -r '.slug')
        name=$(echo "$addon" | jq -r '.name')
        version=$(echo "$addon" | jq -r '.version')
        current_versions["$slug"]="$version"
    done < <(ha addons --raw-json | jq -c '.data.addons[]')
    
    # Check GitHub repositories
    for repo in $(echo "$GITHUB_REPOS" | jq -c '.[]'); do
        local name owner repo_name token
        name=$(echo "$repo" | jq -r '.name')
        owner=$(echo "$repo" | jq -r '.owner')
        repo_name=$(echo "$repo" | jq -r '.repo')
        token=$(echo "$repo" | jq -r '.token // empty')
        
        bashio::log.debug "Checking GitHub repo: ${owner}/${repo_name}"
        
        if latest_version=$(check_github_release "$owner" "$repo_name" "$token"); then
            latest_versions["gh:${owner}/${repo_name}"]="$latest_version"
            
            # Compare with installed version
            if [[ -n "${current_versions["local:${repo_name}"]}" ]]; then
                current_version="${current_versions["local:${repo_name}"]}"
                
                if version_gt "$latest_version" "$current_version"; then
                    updates+=("${name}: ${current_version} → ${latest_version}")
                else
                    no_updates+=("${name}: ${current_version} (latest)")
                fi
            fi
        fi
    done
    
    # Check Gitea instances
    for instance in $(echo "$GITEA_INSTANCES" | jq -c '.[]'); do
        local name url owner token verify_ssl
        name=$(echo "$instance" | jq -r '.name')
        url=$(echo "$instance" | jq -r '.url')
        owner=$(echo "$instance" | jq -r '.owner')
        token=$(echo "$instance" | jq -r '.token // empty')
        verify_ssl=$(echo "$instance" | jq -r '.verify_ssl // true')
        
        bashio::log.debug "Checking Gitea instance: ${name} (${url})"
        
        # Get repositories
        local api_url="${url}/api/v1/users/${owner}/repos"
        local headers=() curl_opts=()
        
        if [[ -n "$token" ]]; then
            headers+=("-H" "Authorization: token ${token}")
        fi
        
        if [[ "$verify_ssl" == "false" ]]; then
            curl_opts+=("-k")
        fi
        
        repos=$(curl -sS "${curl_opts[@]}" "${headers[@]}" "$api_url" | jq -r '.[].name') || {
            bashio::log.warning "Failed to get repositories from Gitea: ${url}"
            continue
        }
        
        for repo_name in $repos; do
            bashio::log.debug "Checking Gitea repo: ${owner}/${repo_name}"
            
            if latest_version=$(check_gitea_release "$url" "$owner" "$repo_name" "$token" "$verify_ssl"); then
                latest_versions["gitea:${owner}/${repo_name}"]="$latest_version"
                
                # Compare with installed version
                if [[ -n "${current_versions["local:${repo_name}"]}" ]]; then
                    current_version="${current_versions["local:${repo_name}"]}"
                    
                    if version_gt "$latest_version" "$current_version"; then
                        updates+=("${name}/${repo_name}: ${current_version} → ${latest_version}")
                    else
                        no_updates+=("${name}/${repo_name}: ${current_version} (latest)")
                    fi
                fi
            fi
        done
    done
    
    # Generate report
    generate_report "${#updates[@]}" "${updates[*]}" "${no_updates[*]}"
}

# =================
# REPORT GENERATION
# =================
generate_report() {
    local update_count=$1 updates=$2 no_updates=$3
    local message priority
    
    message="⚡ Addon Update Report ⚡\n"
    message+="📅 $(date +"%Y-%m-%d %H:%M:%S")\n\n"
    
    if [[ $update_count -gt 0 ]]; then
        message+="🔄 Updates Available ($update_count):\n"
        for update in ${updates}; do
            message+="- ${update}\n"
        done
        message+="\n"
        priority=8
    else
        message+="✅ All addons are up to date\n\n"
        priority=5
    fi
    
    if [[ ${#no_updates[@]} -gt 0 ]]; then
        message+="📋 Current Versions:\n"
        for version in ${no_updates}; do
            message+="- ${version}\n"
        done
    fi
    
    # Send notification
    send_gotify "Addon Update Report" "$message" "$priority"
}

# ===========
# MAIN LOOP
# ===========
bashio::log.info "Starting update monitoring with ${CHECK_INTERVAL}s interval"
while true; do
    perform_checks
    sleep "$CHECK_INTERVAL"
done
