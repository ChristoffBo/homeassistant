#!/usr/bin/env bash
set -e

# Best-effort system update (won't fail if offline)
apt-get update || true
apt-get upgrade -y || true

# Ensure persistent directories exist
mkdir -p /config/adguard/conf
mkdir -p /config/adguard/work

# Link AdGuard paths to persistent storage
ln -sfn /config/adguard/conf /opt/adguardhome/conf
ln -sfn /config/adguard/work /opt/adguardhome/work

# Read options.json for configured ports
DNS_PORT=$(jq -r '.dns_port // 53' /data/options.json)
SETUP_PORT=$(jq -r '.setup_port // 3000' /data/options.json)
WEB_PORT=$(jq -r '.web_port // 80' /data/options.json)

echo "Starting AdGuardHome with:"
echo "  DNS Port: ${DNS_PORT}"
echo "  Setup Port: ${SETUP_PORT}"
echo "  Web Port: ${WEB_PORT}"

# Execute AdGuardHome with correct ports
exec /AdGuardHome \
  --config /opt/adguardhome/conf/AdGuardHome.yaml \
  --work-dir /opt/adguardhome/work \
  --port ${WEB_PORT} \
  --setup-port ${SETUP_PORT} \
  --dns-port ${DNS_PORT}
