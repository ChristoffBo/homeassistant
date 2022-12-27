# Home assistant add-on: Mimic3-tts-server


## About

This addon is based on Mimic - The Mycroft TTS Engine.

## Installation

The installation of this add-on is pretty straightforward and not different in
comparison to installing any other Hass.io add-on.

1. [Add my Hass.io add-ons repository][repository] to your Hass.io instance.
1. Install this add-on.
1. Click the `Save` button to store your configuration.
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.


## Configuration

```
port : 59125 (or the port you changed it to)

HomeAssistant : Add the following to your config.yaml or tts.yaml

                - Platform: marytts
                  host: (Your homeassistant IP)
                  port: 59125
                  voice: en_UK/apope_low (any of the supported voices can be used)
```

Webui can be found at `<your-ip>:port`.

[repository]: https://github.com/ChristoffBo/homeassistant/
