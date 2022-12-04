# Home assistant add-on: Filebrowser

- Latest version : https://github.com/alexbelgium/hassio-addons

## About

Web based files browser.
This addon is based on the [docker image](https://hub.docker.com/r/hurlenko/filebrowser) from hurlenko.

## Configuration

Webui can be found at <http://your-ip:8080>.
Default username: "admin" and password: "admin"

Network disk is mounted to /share/storagecifs

```yaml
ssl: true/false
certfile: fullchain.pem #ssl certificate
keyfile: privkey.pem #sslkeyfile
NoAuth: true/false #Remove password. Resets database when changed.
smbv1: false # Should smbv1 be used instead of 2.1+?
localdisks: sda1 #put the hardware name of your drive to mount separated by commas, or its label. Ex: sda1, sdb1, MYNAS...
networkdisks: "//SERVER/SHARE" # optional, list of smbv2/3 servers to mount, separated by commas
cifsusername: "username" # optional, smb username, same for all smb shares
cifspassword: "password" # optional, smb password, same for all smb shares)
base_folder: root folder # optional, default is /
```

## Installation

The installation of this add-on is pretty straightforward and not different in
comparison to installing any other Hass.io add-on.

1. [Add my Hass.io add-ons repository][repository] to your Hass.io instance.
1. Install this add-on.
1. Click the `Save` button to store your configuration.
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.
1. Carefully configure the add-on to your preferences, see the official documentation for for that.

## Support

Create an issue on github, or ask on the [home assistant thread](https://community.home-assistant.io/t/home-assistant-addon-filebrowser/282108/3)

[repository]: https://github.com/alexbelgium/hassio-addons
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[armv7-shield]: https://img.shields.io/badge/armv7-yes-green.svg
