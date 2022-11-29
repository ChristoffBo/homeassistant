# OpenVPN Client Add-On

This is an Add-On for [Home Assistant](https://www.home-assistant.io) 

## Installation

Move your client.ovpn file to /share folder on your server.
Create a file in /share folder called auth.txt and add your username and password on the first and second line.
edit your ovpn file and add the following auth-user-pass /share/auth.txt

Click on OpenVPN Client, then INSTALL and Start.

# Home assistant add-on: Technitium-DNS 


## About

This addon is based on the Technitium-DNS docker image.

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
port : 5380 #port you want to run on.
```

Webui can be found at `<your-ip>:port`.

[repository]: https://github.com/ChristoffBo/homeassistant/
