#!/bin/sh

mkdir -p /data/technitium
/usr/bin/dotnet /etc/dns/DnsServerApp.dll /data/technitium

echo ""
echo "======================================================================================"
echo ""Starting Technitium DNS Server                                                      ""
echo "======================================================================================"

exit 1

