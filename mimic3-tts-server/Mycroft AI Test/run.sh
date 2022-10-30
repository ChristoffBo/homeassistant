#!/bin/bash



echo ""
echo "======================================================================================"
echo ""Starting Mimic TTS Server                                                      ""
echo "======================================================================================"

echo ""
echo "======================================================================================"
echo ""Checking Voices And Uncompressing                                                   ""
echo "======================================================================================"
cd ~/
git clone https://github.com/MycroftAI/mycroft-core.git
cd mycroft-core
basg dev_setup.sh


./start-mycroft.sh all




exit 1
