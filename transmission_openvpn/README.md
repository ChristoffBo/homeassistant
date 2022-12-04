# Home assistant add-on: Transmission Openvpn

- Latest version : https://github.com/alexbelgium/hassio-addons

## About

Transmission is a bittorrent client.
This addon is based on the [Haugene docker image](https://github.com/haugene/docker-transmission-openvpn).

## Installation

The installation of this add-on is pretty straightforward and not different in
comparison to installing any other Hass.io add-on.


1. Install this add-on.
1. Click the `Save` button to store your configuration.
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.
1. Carefully configure the add-on to your preferences, see the official documentation for for that.

## Configuration

Options : see https://github.com/haugene/docker-transmission-openvpn for documentation

TRANSMISSION_V3_UPDATE: updates to v3. Remove and add all torrents due to transmission changes

For setting a custom openvpn file, you should flag the "OPENVPN_CUSTOM_PROVIDER" field and reference the path of the \*.ovpn file in the "OPENVPN_CUSTOM_PROVIDER_OVPN_LOCATION" field.

Complete transmission options are in /config/addons_config/transmission (make sure addon is stopped before modifying it as Transmission writes its ongoing values when stopping and could erase your changes)

Webui can be found at `<your-ip>:9091`.

