#!/usr/bin/with-contenv bashio

# Activate virtual environment
source /venv/bin/activate

# Start the application
cd /app
exec python3 -m app.main