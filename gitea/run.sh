#!/usr/bin/with-contenv bashio

# ==============================================================================
# Set Default Values (Fallback if not set in GUI)
# ==============================================================================
export USER_UID=${USER_UID:-1000}
export USER_GID=${USER_GID:-1000}

# Get GUI config or use defaults
DOMAIN=$(bashio::config 'domain' 'homeassistant.local')
LOG_LEVEL=$(bashio::config 'log_level' 'info')
SSH_ENABLED=$(bashio::config 'ssh_enabled' 'true')
DISABLE_REG=$(bashio::config 'disable_registration' 'false')
APP_NAME=$(bashio::config 'app_name' 'Gitea on Home Assistant')

# Core Settings
export GITEA__server__PROTOCOL="http"
export GITEA__server__DOMAIN="${DOMAIN}"
export GITEA__server__HTTP_PORT=3000
export GITEA__server__SSH_PORT=2222
export GITEA__server__ROOT_URL="http://${DOMAIN}:3000/"
export GITEA__server__DISABLE_SSH="$([ "${SSH_ENABLED}" = "true" ] && echo "false" || echo "true")"

# Database Configuration
DB_TYPE=$(bashio::config 'db_type' 'sqlite3')
export GITEA__database__DB_TYPE="${DB_TYPE}"

case "${DB_TYPE}" in
  mysql|postgres)
    export GITEA__database__HOST=$(bashio::config 'db_host' '')
    export GITEA__database__NAME=$(bashio::config 'db_name' 'gitea')
    export GITEA__database__USER=$(bashio::config 'db_user' 'gitea')
    export GITEA__database__PASSWD=$(bashio::config 'db_pass' '')
    ;;
  *)
    export GITEA__database__PATH="/data/gitea/data/gitea.db"
    ;;
esac

# Application Settings
export GITEA__repository__ROOT="/data/gitea/repositories"
export GITEA__security__DISABLE_REGISTRATION="${DISABLE_REG}"
export GITEA__log__LEVEL="${LOG_LEVEL}"
export GITEA__app__NAME="${APP_NAME}"

# ==============================================================================
# Directory Setup
# ==============================================================================
mkdir -p /data/gitea/{conf,data,logs,repositories}
chown -R ${USER_UID}:${USER_GID} /data/gitea
chmod -R 750 /data/gitea

# ==============================================================================
# Generate Configuration
# ==============================================================================
{
  # Application Info
  echo "[app]"
  env | grep ^GITEA__app__ | sed 's/GITEA__app__//' | awk -F= '{print $1 " = " $2}'
  
  # Server Section
  echo -e "\n[server]"
  env | grep ^GITEA__server__ | sed 's/GITEA__server__//' | awk -F= '{print $1 " = " $2}'
  
  # Database Section
  echo -e "\n[database]"
  env | grep ^GITEA__database__ | sed 's/GITEA__database__//' | awk -F= '{print $1 " = " $2}'
  
  # Repository Section
  echo -e "\n[repository]"
  env | grep ^GITEA__repository__ | sed 's/GITEA__repository__//' | awk -F= '{print $1 " = " $2}'
  
  # Security Section
  echo -e "\n[security]"
  env | grep ^GITEA__security__ | sed 's/GITEA__security__//' | awk -F= '{print $1 " = " $2}'
  
  # Logging Section
  echo -e "\n[log]"
  env | grep ^GITEA__log__ | sed 's/GITEA__log__//' | awk -F= '{print $1 " = " $2}'
} > /data/gitea/conf/app.ini

# ==============================================================================
# Start Gitea
# ==============================================================================
exec /usr/local/bin/gitea web --config /data/gitea/conf/app.ini