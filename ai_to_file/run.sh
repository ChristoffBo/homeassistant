#!/usr/bin/with-contenv bashio

cd /app || exit
exec python3 -m app.main