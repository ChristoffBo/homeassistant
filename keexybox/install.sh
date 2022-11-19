#!/bin/sh




echo ""
echo "===================================================================================="
echo ""Checking KeexyBox DNS Server Install                                            ""
echo "===================================================================================="

DIR="/keexybox_21.04.2_amd64_debian10/"
if [ -d "$DIR" ]; then

  echo "Keexybox is Already Installed"
else

curl -J -L -o /tmp/keexybox.tar.gz https://download.keexybox.org/amd64/keexybox_21.04.2_amd64_debian10.tar.gz
cd tmp
tar xzf /tmp/keexybox.tar.gz


cd keexybox_21.04.2_amd64_debian10
./install.sh

exit 1

