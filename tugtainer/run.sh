#!/usr/bin/env bash
set -e

echo "[Tugtainer] Starting manager in Home Assistant add-on mode…"

# Ensure timezone is set
export TZ=${TZ:-Africa/Johannesburg}

# Launch Tugtainer (manager only)
echo "[Tugtainer] Launching server on ports 9000/8443"
exec /app/tugtainer