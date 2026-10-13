#!/bin/sh
# Starts the Ingress forwarder (restarted if it ever exits), then the hub itself.
(
  while true; do
    node /addon/ingress.js
    sleep 5
  done
) &
cd /app || exit 1
exec node src/index.js
