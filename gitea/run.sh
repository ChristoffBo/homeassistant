#!/bin/sh
set -e

# Create directory structure
mkdir -p /data/gitea/{conf,data,logs,repositories}

# Generate default config if missing
if [ ! -f /data/gitea/conf/app.ini ]; then
  cat > /data/gitea/conf/app.ini <<'EOL'
[server]
DOMAIN = localhost
HTTP_PORT = 3000
SSH_PORT = 2222
ROOT_URL = http://localhost:3000/

[database]
DB_TYPE = sqlite3
PATH = /data/gitea/data/gitea.db

[repository]
ROOT = /data/gitea/repositories

[security]
INSTALL_LOCK = false
EOL
fi

# Fix permissions
chown -R git:git /data/gitea

# Start Gitea
exec su-exec git /usr/local/bin/gitea web --config /data/gitea/conf/app.ini