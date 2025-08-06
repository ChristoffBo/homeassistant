#!/bin/bash
# Initialize ZeroTier controller
CONFIG_DIR="/config"
ZT_DIR="$CONFIG_DIR/zerotier"
CONTROLLER_TOKEN=$(jq -r '.controller_token' /data/options.json)

# Create ZeroTier directory
mkdir -p "$ZT_DIR"

# Symlink ZeroTier data to persistent storage
ln -sf "$ZT_DIR" /var/lib/zerotier-one

# Ensure TUN module is loaded
modprobe tun || echo "Warning: TUN module not loaded. Ensure it is enabled on the host."

# Generate controller token if not provided
if [ -z "$CONTROLLER_TOKEN" ] || [ "$CONTROLLER_TOKEN" = "!secret zerotier_token" ]; then
    CONTROLLER_TOKEN=$(cat /var/lib/zerotier-one/authtoken.secret 2>/dev/null || echo "generated_token_$(openssl rand -hex 16)")
    echo "$CONTROLLER_TOKEN" > /var/lib/zerotier-one/authtoken.secret
    chmod 600 /var/lib/zerotier-one/authtoken.secret
fi

# Ensure ZeroUI config uses the token
sed -i "s|ZT_TOKEN:.*|ZT_TOKEN: $CONTROLLER_TOKEN|" /app/zero-ui/config.yaml