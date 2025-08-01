#!/usr/bin/with-contenv sh

# Activate venv
. /venv/bin/activate

# Execute as PID 1 through s6
exec /venv/bin/python -m app.main