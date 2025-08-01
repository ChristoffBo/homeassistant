#!/usr/bin/with-contenv bashio

# Activate virtual environment
source /venv/bin/activate

# Change to app directory
cd /app || exit

# Execute main.py
exec python3 main.py