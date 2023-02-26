#!/bin/sh

curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel STS

mkdir -p /data/technitium
/usr/bin/dotnet /opt/technitium/dns/DnsServerApp.dll /data/technitium


exit 1

