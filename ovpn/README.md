




!OPVPN Logo ](https://github.com/ChristoffBo/homeassistant/blob/main/ovpn/logo.png)






# Home assistant add-on: OpenVpn Client


## About

This addon is based on OpenVpn.

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
Move your client.ovpn file to /share folder on your HomeAssistant server.

Create a file in /share folder called auth.txt and add your username and password on the first and second lines.

edit your ovpn file and add the following auth-user-pass /share/auth.txt

Start the Addon and check the logs.
```



[repository]: https://github.com/ChristoffBo/homeassistant/
