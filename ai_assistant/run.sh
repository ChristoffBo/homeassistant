#!/usr/bin/with-contenv bashio

# Activate virtual environment
source /venv/bin/activate

# Start the application through s6
exec /venv/bin/python /app/main.py