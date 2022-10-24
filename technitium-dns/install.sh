#!/bin/sh




echo ""
echo "===================================================================================="
echo ""Checking Technitium DNS Server Install                                            ""
echo "===================================================================================="

DIR="/data/technitium/"
if [ -d "$DIR" ]; then

  echo "Technitium DNS is Already Installed"
else
  mkdir -p /data/technitium/
  cd /data/technitium/
  curl -J -L -o /tmp/DnsServerPortable.tar.gz https://download.technitium.com/dns/DnsServerPortable.tar.gz
  cd /data/technitium
  tar -zxf /tmp/DnsServerPortable.tar.gz -C /data/technitium/
  \
  timedatectl set-timezone Africa/Johannesburg  
    
    
  
  
  echo "Technitium not installed.Installing."
fi


echo ""
echo "======================================================================================"
echo ""Starting Technitium DNS Server                                                      ""
echo "======================================================================================"



cd /data/technitium/
./start.sh

exit 1

