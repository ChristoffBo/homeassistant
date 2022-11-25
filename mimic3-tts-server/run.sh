#!/bin/bash

#!/bin/bash
echo ""
echo "======================================================================================"
echo ""Preloading Voices UK and Afrikaans                                             ""
echo "======================================================================================"

if [ -d "/root/.local/share/mycroft/mimic3/voices/en_UK/" ] 
then
    echo "UK Voice Already Preloaded" 
else
    echo "Preloading UK Voice"
    mimic3-download 'en_UK/apope_low*' 
    
fi


if [ -d "/root/.local/share/mycroft/mimic3/voices/af_ZA/" ] 
then
    echo "Afrikaans Voice Already Preloaded" 
else
    echo "Preloading Afrikaans Voice"
    mimic3-download 'af_ZA/*'
    
fi





echo ""
echo "======================================================================================"
echo ""Starting Mimic TTS Server                                                           ""
echo "======================================================================================"



mimic3-server --preload-voice en_UK/apope_low --cache-dir /data/cache/


echo ""
echo "======================================================================================"
echo ""Mimic TTS Server  Started                                                           ""
echo "======================================================================================"




exit 1
