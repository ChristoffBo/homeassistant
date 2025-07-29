#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH=/data/options.json

# Colored log output
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[0;33m"
COLOR_RED="\033[0;31m"
COLOR_RESET="\033[0m"

log() {
  local color="$1"
  shift
  echo -e "${color}[Gitea Add-on] $*${COLOR_RESET}"
}

log "${COLOR_GREEN}" "Reading configuration from ${CONFIG_PATH}..."

# Read GUI-configured options
DOMAIN=$(jq -r '.domain' "$CONFIG_PATH")
APP_NAME=$(jq -r '.app_name' "$CONFIG_PATH")
DISABLE_REGISTRATION=$(jq -r '.disable_registration' "$CONFIG_PATH")
SSH_ENABLED=$(jq -r '.ssh_enabled' "$CONFIG_PATH")
LOG_LEVEL=$(jq -r '.log_level' "$CONFIG_PATH")

# Export ENV for Gitea
export USER_UID=1000
export USER_GID=1000
export GITEA__server__PROTOCOL=http
export GITEA__server__DOMAIN="${DOMAIN}"
export GITEA__server__ROOT_URL="http://${DOMAIN}:3001/"
export GITEA__server__HTTP_PORT=3000
export GITEA__server__SSH_PORT=2222
export GITEA__app_name="${APP_NAME}"
export GITEA__service__DISABLE_REGISTRATION="${DISABLE_REGISTRATION}"
export GITEA__log__LEVEL="${LOG_LEVEL}"
export GITEA__database__DB_TYPE=sqlite3
export GITEA__database__PATH=/data/gitea/data/gitea.db
export GITEA__repository__ROOT=/data/gitea/repositories

# SSH toggle (optional, handled internally by Gitea if needed)
if [ "$SSH_ENABLED" = "false" ]; then
  log "${COLOR_YELLOW}" "Disabling SSH in Gitea config."
  export GITEA__server__START_SSH_SERVER=false
else
  export GITEA__server__START_SSH_SERVER=true
fi

log "${COLOR_GREEN}" "Launching Gitea..."
exec /usr/bin/entrypoint