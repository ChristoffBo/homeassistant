#!/bin/bash

mkdir -p /home/user/.local/share/mycroft/mimic3
chmod a+rwx /home/user.local/share/mycroft/mimic3

echo ""
echo "======================================================================================"
echo ""Starting Mimic TTS Server                                                      ""
echo "======================================================================================"


mimic3-server --preload-voice en_US/ljspeech_low --cache-dir /data/cache/

exit 1
