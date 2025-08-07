#!/usr/bin/env bashio

# Start the Node.js server for the UI
cd /app
npm start &

# Keep the container running
wait
