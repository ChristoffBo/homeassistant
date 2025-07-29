#!/bin/sh
set -e

mkdir -p /data/gitea/{conf,data,logs,repositories}
[ ! -f /data/gitea/conf/app.ini ] && cp /etc/gitea/app.ini /data/gitea/conf/
chown -R git:git /data/gitea
exec su-exec git /usr/local/bin/gitea web --config /data/gitea/conf/app.ini