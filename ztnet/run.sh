#!/bin/bash

# Init DB dir
mkdir -p /data/postgres
chown -R postgres:postgres /data/postgres

# Init ZT dir
mkdir -p /data/zerotier-one
chown -R root:root /data/zerotier-one

# Start everything with supervisord
exec /usr/bin/supervisord -c /etc/supervisord.conf
