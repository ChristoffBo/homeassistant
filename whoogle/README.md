# Home assistant add-on: whoogle-search

- Latest version : https://github.com/alexbelgium/hassio-addons

## About

[whoogle-search](https://github.com/benbusby/whoogle-search) is a Self-hosted, ad-free, privacy-respecting metasearch engine.
This addon is based on the docker image https://hub.docker.com/r/benbusby/whoogle-search/tags

## Configuration

Webui can be found at <http://your-ip:PORT>.
Configurations can be done through the app webUI, except for the following options

Options can be configured through two ways :

- Addon options

```yaml
"CONFIG_LOCATION": location of the config.yaml (see below)
```

- Config.yaml

Custom env variables can be added to the config.yaml file referenced in the addon options. Full env variables can be found here : https://github.com/benbusby/whoogle-search#environment-variables. It must be entered in a valid yaml format, that is verified at launch of the addon.

## Installation

The installation of this add-on is pretty straightforward and not different in comparison to installing any other add-on.

1. Add my add-ons repository to your home assistant instance (in supervisor addons store at top right, or click button below if you have configured my HA)
   [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Falexbelgium%2Fhassio-addons)
1. Install this add-on.
1. Click the `Save` button to store your configuration.
1. Set the add-on options to your preferences
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.
1. Open the webUI and adapt the software options

## Support

Create an issue on github

## Illustration

![illustration](https://github.com/benbusby/whoogle-search/raw/main/docs/screenshot_desktop.jpg)

[repository]: https://github.com/alexbelgium/hassio-addons
