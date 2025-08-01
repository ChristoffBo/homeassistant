#!/usr/bin/with-contenv bashio

# Wait for full system initialization
bashio::log.info "Waiting for system to stabilize..."
sleep 30

# Activate virtual environment
source /venv/bin/activate

# Start Gunicorn with production settings
bashio::log.info "Starting application server..."
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