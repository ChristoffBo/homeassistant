#!/usr/bin/with-contenv bashio

# Wait for system to fully initialize
sleep 20

# Activate virtual environment
source /venv/bin/activate

# Start Gunicorn with production settings
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --worker-class sync \
    --workers 1 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --preload \
    --forwarded-allow-ips="*" \
    app.main:app