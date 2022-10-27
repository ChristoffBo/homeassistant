#!/bin/bash

echo ""
echo "===================================================================================="
echo ""Checking Mimic Server Install                                                     ""
echo "===================================================================================="

FILE="/tmp/mycroft-mimic3-tts_0.2.3_amd64.deb/"
if [ -d "$FILE" ]; then

 echo "Mimic is Already Installed"
else
cd /tmp
apt install ./mycroft-mimic3-tts_0.2.3_amd64.deb
 echo "Mimic not installed.Installing."
fi

echo ""
echo "======================================================================================"
echo ""Starting Mimic TTS Server                                                      ""
echo "======================================================================================"

cd /usr/bin

mimic3-server

exit 1
