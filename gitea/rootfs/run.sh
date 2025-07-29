#!/usr/bin/with-contenv bashio

# Create directories with correct permissions
mkdir -p /data/gitea/{conf,data,logs,repositories}
chown -R ${USER_UID}:${USER_GID} /data/gitea
chmod -R 750 /data/gitea

# Process environment variables into app.ini
for var in $(printenv | grep ^GITEA__); do
  section_key="${var#GITEA__}"
  section="${section_key%%__*}"
  key="${section_key#*__}"
  key="${key%%=*}"
  value="${var#*=}"
  
  crudini --set /data/gitea/conf/app.ini "${section}" "${key}" "${value}"
done

# Apply Home Assistant specific configs
crudini --set /data/gitea/conf/app.ini "" APP_NAME "$(bashio::config 'app_name')"
crudini --set /data/gitea/conf/app.ini "security" DISABLE_REGISTRATION "$(bashio::config 'disable_registration')"
crudini --set /data/gitea/conf/app.ini "log" LEVEL "$(bashio::config 'log_level')"
crudini --set /data/gitea/conf/app.ini "server" DISABLE_SSH "$(! bashio::config 'ssh_enabled'; echo $?)"
crudini --set /data/gitea/conf/app.ini "server" DOMAIN "$(bashio::config 'domain')"

# Start using official image's entrypoint
exec /usr/bin/entrypoint /usr/local/bin/gitea web --config /data/gitea/conf/app.ini