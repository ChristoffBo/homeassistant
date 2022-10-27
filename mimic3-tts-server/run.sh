#!/bin/bash

echo ""
echo "===================================================================================="
echo ""Checking Mimic Server Install                                                     ""
echo "===================================================================================="

FILE="/tmp/mycroft-mimic3-tts_0.2.3_amd64.deb"
if [ -f "$FILE" ]; then

 echo "Mimic is Already Installed"
else
echo "Mimic not installed.Installing."
curl -J -L -o /tmp/mycroft-mimic3-tts_0.2.3_amd64.deb \
        "https://github.com/MycroftAI/mimic3/releases/download/release%2Fv0.2.3/mycroft-mimic3-tts_0.2.3_amd64.deb"
mkdir -p /data/tts/        
mkdir -p /data/cache/
chmod 77 /data/tts/
chmod 777 /data/cache/
chmod 777 /var/lib/apt/lists/auxfiles
chmod 777 /var/cache/apt
cd /tmp
dpkg-deb -x mycroft-mimic3-tts_0.2.3_amd64.deb /data/tts/
#dpkg -i /tmp/mycroft-mimic3-tts_0.2.3_amd64.deb
apt-get install -f
fi

echo ""
echo "======================================================================================"
echo ""Starting Mimic TTS Server                                                      ""
echo "======================================================================================"

cd /data/tts

mimic3-server --preload-voice en_US/ljspeech_low --cache-dir /data/cache/

exit 1
