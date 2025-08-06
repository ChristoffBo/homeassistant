#!/bin/bash
set -e

# Run initialization
/app/init.sh

# Start ZeroTier in controller mode
zerotier-one -d

# Serve static UI
cd /app/www
python3 -m http.server 80