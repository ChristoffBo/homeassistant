#!/bin/bash
cd /tmp
apt install ./mycroft-mimic3-tts_0.2.3_amd64.deb

cd /usr/bin

mimic3-server
