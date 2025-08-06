#!/bin/bash
set -e

CONFIG_DIR="/config"
ZT_DIR="$CONFIG_DIR/zerotier"
OPTIONS_FILE="/data/options.json"
CONFIG_FILE="/app/zero-ui-config.yaml"

CONTROLLER_TOKEN=$(jq -r '.controller_token' "$OPTIONS_FILE")
ADMIN_USERNAME=$(jq -r '.admin_username' "$OPTIONS_FILE")
ADMIN_PASSWORD=$(jq -r '.admin_password' "$OPTIONS_FILE")

# Setup persistent storage
mkdir -p "$ZT_DIR"
ln -sf "$ZT_DIR" /var/lib/zerotier-one

echo "NOTE: Skipping modprobe. HAOS containers do not support loading modules."

# Generate token if not provided
if [ -z "$CONTROLLER_TOKEN" ] || [ "$CONTROLLER_TOKEN" = "null" ]; then
    CONTROLLER_TOKEN=$(cat /var/lib/zerotier-one/authtoken.secret 2>/dev/null || echo "generated_token_$(openssl rand -hex 16)")
    echo "$CONTROLLER_TOKEN" > /var/lib/zerotier-one/authtoken.secret
    chmod 600 /var/lib/zerotier-one/authtoken.secret
fi

# Update config values dynamically
if grep -q "ZT_TOKEN:" "$CONFIG_FILE"; then
    sed -i "s|ZT_TOKEN:.*|ZT_TOKEN: $CONTROLLER_TOKEN|" "$CONFIG_FILE"
else
    echo "ZT_TOKEN: $CONTROLLER_TOKEN" >> "$CONFIG_FILE"
fi

if grep -q "ZU_DEFAULT_USERNAME:" "$CONFIG_FILE"; then
    sed -i "s|ZU_DEFAULT_USERNAME:.*|ZU_DEFAULT_USERNAME: '$ADMIN_USERNAME'|" "$CONFIG_FILE"
else
    echo "ZU_DEFAULT_USERNAME: '$ADMIN_USERNAME'" >> "$CONFIG_FILE"
fi

if grep -q "ZU_DEFAULT_PASSWORD:" "$CONFIG_FILE"; then
    sed -i "s|ZU_DEFAULT_PASSWORD:.*|ZU_DEFAULT_PASSWORD: '$ADMIN_PASSWORD'|" "$CONFIG_FILE"
else
    echo "ZU_DEFAULT_PASSWORD: '$ADMIN_PASSWORD'" >> "$CONFIG_FILE"
fi

# Ensure CLI is accessible
if [ ! -f /usr/bin/zerotier-cli ]; then
    ln -s /usr/sbin/zerotier-one /usr/bin/zerotier-cli
fi