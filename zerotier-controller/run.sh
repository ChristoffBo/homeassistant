#!/bin/bash
set -e

# Run setup
/app/init.sh

# Start ZeroTier in controller mode
zerotier-one -d

# Serve UI from static frontend
cd /app/www
python3 -m http.server 3000