#!/usr/bin/with-contenv sh

# Activate virtual environment
. /venv/bin/activate

# Start application as PID 1
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --worker-class sync \
    --threads 1 \
    --timeout 120 \
    app.main:app