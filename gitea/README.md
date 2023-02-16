![Logo ](https://github.com/ChristoffBo/homeassistant/blob/main/gitea/logo.png)
# Home assistant add-on: Gitea



## About

Various tweaks and configuration options addition.
This addon is based on the [docker image](https://hub.docker.com/r/gitea/gitea).

## Configuration

```yaml
certfile: fullchain.pem #ssl certificate, must be located in /ssl
keyfile: privkey.pem #sslkeyfile, must be located in /ssl
ssl: should the app use https or not
APP_NAME: name of the app
DOMAIN: domain to be reached # default : homeassistant.local
ROOT_URL: customize root_url, should not be needed unless specific needs
```

Webui can be found at `<your-ip>:port`.

## Installation

The installation of this add-on is pretty straightforward and not different in
comparison to installing any other Hass.io add-on.

1. [Add my Hass.io add-ons repository][repository] to your Hass.io instance.
1. Install this add-on.
1. Click the `Save` button to store your configuration.
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.
1. Go to the webui, where you will initialize the app
1. Restart the addon, to apply any option that should be applied

[repository]: https://github.com/alexbelgium/hassio-addons
