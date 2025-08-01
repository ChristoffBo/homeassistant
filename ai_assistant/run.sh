#!/usr/bin/with-contenv bashio

# Activate virtual environment
source /venv/bin/activate

# Start Gunicorn with web UI
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --worker-class sync \
    --workers 1 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --forwarded-allow-ips="*" \
    app.main:app