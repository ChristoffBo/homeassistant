#!/bin/sh
# WG Easy add-on start script (wg-easy 15).
# wg-easy keeps its database and WireGuard config in /etc/wireguard; that
# folder is linked to /data/wireguard, which the Supervisor keeps.
set -e

OPTS=/data/options.json
opt() {
    node -e "try{const o=JSON.parse(require('fs').readFileSync('$OPTS','utf8'));const v=o['$1'];if(v!==undefined&&v!==null)process.stdout.write(String(v))}catch(e){}"
}

mkdir -p /data/wireguard
if [ -d /etc/wireguard ] && [ ! -L /etc/wireguard ]; then
    # first start of a fresh image: keep anything the image shipped, never overwrite saved data
    cp -an /etc/wireguard/. /data/wireguard/ 2>/dev/null || true
    rm -rf /etc/wireguard
fi
ln -sfn /data/wireguard /etc/wireguard

INSECURE="$(opt insecure)"
[ -n "$INSECURE" ] || INSECURE=true
DISABLE_IPV6="$(opt disable_ipv6)"
[ -n "$DISABLE_IPV6" ] || DISABLE_IPV6=false
export INSECURE DISABLE_IPV6
echo "WG Easy: INSECURE=${INSECURE} DISABLE_IPV6=${DISABLE_IPV6}, data in /data/wireguard"

cd /app
exec /usr/bin/dumb-init node server/index.mjs
