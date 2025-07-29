#!/usr/bin/with-contenv bashio

# Create directories
mkdir -p /data/gitea/{conf,data,logs,repositories}

# Generate config if missing
if [ ! -f /data/gitea/conf/app.ini ]; then
    cp /etc/gitea/app.ini /data/gitea/conf/app.ini
fi

# Configure SSH
crudini --set /data/gitea/conf/app.ini "server" \
    DISABLE_SSH "$(! bashio::config 'ssh_enabled'; echo $?)"

# Set permissions
chown -R git:git /data/gitea
chmod -R 750 /data/gitea

# Start Gitea
exec s6-setuidgid git \
    /usr/local/bin/gitea web --config /data/gitea/conf/app.ini