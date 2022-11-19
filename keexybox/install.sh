#!/bin/sh




echo ""
echo "===================================================================================="
echo ""Checking KeexyBox DNS Server Install                                            ""
echo "===================================================================================="

#DIR="/keexybox_21.04.2_amd64_debian10/"
#if [ -d "$DIR" ]; then
#
#  echo "Technitium DNS is Already Installed"
#else
#  mkdir -p /data/technitium/
#  cd /data/technitium/
#  curl -J -L -o /tmp/DnsServerPortable.tar.gz https://download.technitium.com/dns/DnsServerPortable.tar.gz
#  cd /data/technitium
#  tar -zxf /tmp/DnsServerPortable.tar.gz -C /data/technitium/
#  \
  timedatectl set-timezone Africa/Johannesburg  
#    
#    
#  
#  
#  echo "Technitium not installed.Installing."
#fi
#
#
#
#echo ""
#echo "======================================================================================"
#echo ""Starting Technitium DNS Server                                                      ""
#echo "======================================================================================"

cd ~
wget https://download.keexybox.org/amd64/keexybox_21.04.2_amd64_debian10.tar.gz

tar xzf keexybox_21.04.2_amd64_debian10.tar.gz
cd keexybox_21.04.2_amd64_debian10
./install.sh

exit 1

