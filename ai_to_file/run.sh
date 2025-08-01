#!/usr/bin/with-contenv bashio

# Activate virtual environment
source /venv/bin/activate

cd /app || exit
exec python3 -m app.main