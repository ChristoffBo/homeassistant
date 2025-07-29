#!/usr/bin/with-contenv bashio

# ==============================================================================
# Environment Variables Configuration
# ==============================================================================

# Set default environment variables
export USER_UID=1000
export USER_GID=1000
export GITEA__server__PROTOCOL="http"
export GITEA__server__DOMAIN="localhost"
export GITEA__server__HTTP_PORT=3001
export GITEA__server__SSH_PORT=2222
export GITEA__server__ROOT_URL="http://localhost:3001/"
export GITEA__database__DB_TYPE="sqlite3"
export GITEA__database__PATH="/data/gitea/data/gitea.db"
export GITEA__repository__ROOT="/data/gitea/repositories"

# ==============================================================================
# Directory Setup
# ==============================================================================

mkdir -p /data/gitea/{conf,data,logs,repositories}
chown -R ${USER_UID}:${USER_GID} /data/gitea
chmod -R 750 /data/gitea

# ==============================================================================
# Configuration Generation
# ==============================================================================

# Generate app.ini from environment variables
cat > /data/gitea/conf/app.ini <<EOL
[server]
PROTOCOL = ${GITEA__server__PROTOCOL}
DOMAIN = ${GITEA__server__DOMAIN}
HTTP_PORT = ${GITEA__server__HTTP_PORT}
SSH_PORT = ${GITEA__server__SSH_PORT}
ROOT_URL = ${GITEA__server__ROOT_URL}
DISABLE_SSH = false

[database]
DB_TYPE = ${GITEA__database__DB_TYPE}
PATH = ${GITEA__database__PATH}

[repository]
ROOT = ${GITEA__repository__ROOT}

[log]
LEVEL = $(bashio::config 'log_level')
EOL

# ==============================================================================
# Service Startup
# ==============================================================================

exec /usr/local/bin/gitea web --config /data/gitea/conf/app.ini