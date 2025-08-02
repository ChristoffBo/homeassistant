#!/usr/bin/env bash  
CONFIG_PATH=/data/options.json  

# Load configuration  
export REPO_SOURCE=$(jq -r '.repo_source' $CONFIG_PATH)  
export ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications' $CONFIG_PATH)  
export GOTIFY_URL=$(jq -r '.gotify_url // empty' $CONFIG_PATH)  
export GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' $CONFIG_PATH)  
export GITEA_API_URL=$(jq -r '.gitea_api_url // empty' $CONFIG_PATH)  
export GITEA_TOKEN=$(jq -r '.gitea_token // empty' $CONFIG_PATH)  
export REPO_PATH=$(jq -r '.repo_path' $CONFIG_PATH)  
export REPO_BRANCH=$(jq -r '.repo_branch' $CONFIG_PATH)  
export ADDON_PATHS=$(jq -r '.addon_paths[]' $CONFIG_PATH)  
export UPDATE_MODE=$(jq -r '.update_mode' $CONFIG_PATH)  
export TIMEOUT=$(jq -r '.timeout' $CONFIG_PATH)  
export LOG_LEVEL=$(jq -r '.log_level' $CONFIG_PATH)  
export VALIDATE_SSL=$(jq -r '.validate_ssl' $CONFIG_PATH)  
export DRY_RUN=$(jq -r '.dry_run' $CONFIG_PATH)  
