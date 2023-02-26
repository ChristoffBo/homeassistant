#!/bin/sh

mkdir -p /data/technitium
/usr/bin/dotnet /opt/technitium/dns/DnsServerApp.dll /data/technitium

exit 1

