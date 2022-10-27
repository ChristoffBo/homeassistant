Mimic - The Mycroft TTS Engine
Build Status codecov.io Coverity Scan

Mimic is a fast, lightweight Text-to-speech engine developed by Mycroft A.I. and VocaliD, based on Carnegie Mellon University’s Flite (Festival-Lite) software. Mimic takes in text and reads it out loud to create a high quality voice.

Official project site: mimic.mycroft.ai
## Example configuration.yaml entry
```yaml
  tts:

  - platform: marytts
    host: "192.168.1.235"
    port: 59125
    voice: en_US/hifi-tts_low
```

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[armhf-shield]: https://img.shields.io/badge/armhf-yes-green.svg
[armv7-shield]: https://img.shields.io/badge/armv7-yes-green.svg
[i386-shield]: https://img.shields.io/badge/i386-yes-green.svg
