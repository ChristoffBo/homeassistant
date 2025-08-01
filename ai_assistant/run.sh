#!/usr/bin/with-contenv bashio

# Load configuration
export DEFAULT_MODEL=$(bashio::config 'default_model')
export CHATGPT_KEY=$(bashio::config 'chatgpt_api_key')
export DEEPSEEK_KEY=$(bashio::config 'deepseek_api_key')
export GITHUB_TOKEN=$(bashio::config 'github_token')
export GITHUB_REPO=$(bashio::config 'github_repo')

cd /app
exec python3 -m app.main
