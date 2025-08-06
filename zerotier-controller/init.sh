#!/bin/bash
set -e

CONFIG_DIR="/config"
ZT_DIR="$CONFIG_DIR/zerotier"
CONTROLLER_TOKEN=$(jq -r '.controller_token' /data/options.json)
CONFIG_FILE="/app/zero-ui-config.yaml"

# Create ZeroTier persistent storage
mkdir -p "$ZT_DIR"
ln -sf "$ZT_DIR" /var/lib/zerotier-one

# Note: modprobe is skipped due to HAOS sandboxing
echo "NOTE: Skipping modprobe. HAOS containers do not support loading modules."

# Generate token if missing
if [ -z "$CONTROLLER_TOKEN" ] || [ "$CONTROLLER_TOKEN" = "!secret zerotier_token" ]; then
    CONTROLLER_TOKEN=$(cat /var/lib/zerotier-one/authtoken.secret 2>/dev/null || echo "generated_token_$(openssl rand -hex 16)")
    echo "$CONTROLLER_TOKEN" > /var/lib/zerotier-one/authtoken.secret
    chmod 600 /var/lib/zerotier-one/authtoken.secret
fi

# Replace token in UI config
if grep -q "ZT_TOKEN:" "$CONFIG_FILE"; then
    sed -i "s|ZT_TOKEN:.*|ZT_TOKEN: $CONTROLLER_TOKEN|" "$CONFIG_FILE"
else
    echo "ZT_TOKEN: $CONTROLLER_TOKEN" >> "$CONFIG_FILE"
fi

# Ensure CLI exists
if [ ! -f /usr/bin/zerotier-cli ]; then
    ln -s /usr/sbin/zerotier-one /usr/bin/zerotier-cli
fi