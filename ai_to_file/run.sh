#!/usr/bin/with-contenv bashio

# Activate virtual environment
source /venv/bin/activate

# Change to app directory and run main.py directly
cd /app || exit
exec python3 /app/main.py