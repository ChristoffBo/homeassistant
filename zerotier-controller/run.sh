#!/bin/bash
# Run initialization script
/app/init.sh

# Start ZeroTier controller
zerotier-one -d

# Start ZeroUI
cd /app/zero-ui
npm start