#!/usr/bin/with-contenv bashio
# ==============================================================================
# Home Assistant Add-on: Addon Updater Enhanced
# ==============================================================================

# Initialize system
bashio::log.info "Starting Addon Updater Enhanced"

# Check configuration
if ! bashio::config.has_value 'github_repos' && ! bashio::config.has_value 'gitea_instances'; then
    bashio::log.fatal "No repositories configured! Please add GitHub or Gitea repositories."
    exit 1
fi

# Validate Gotify configuration
if bashio::config.has_value 'gotify_url'; then
    if ! bashio::config.has_value 'gotify_token'; then
        bashio::log.fatal "Gotify URL provided but token missing!"
        exit 1
    fi
    bashio::log.info "Gotify notifications enabled"
fi

# Set logging level
if bashio::config.true 'verbose_logging'; then
    bashio::log.level "debug"
    bashio::log.debug "Verbose logging enabled"
fi

# Create version cache directory
mkdir -p /data/version_cache
chown root:root /data/version_cache
chmod 755 /data/version_cache

bashio::log.info "Initialization completed successfully"
