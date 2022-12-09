
# Home assistant add-on: emby

- Latest version : https://github.com/alexbelgium/hassio-addons

## About

---

[Bazarr](https://www.bazarr.media/) is a companion application to Sonarr and Radarr that manages and downloads subtitles based on your requirements.
This addon is based on the docker image https://github.com/linuxserver/docker-bazarr

## Configuration

---

Webui can be found at <http://your-ip:PORT>.
Configurations can be done through the app webUI, except for the following options

```yaml
PGID: user
GPID: user
TZ: timezone
localdisks: sda1 #put the hardware name of your drive to mount separated by commas, or its label. Ex: sda1, sdb1, MYNAS...
networkdisks: "//SERVER/SHARE" # optional, list of smb servers to mount, separated by commas
cifsusername: "username" # optional, smb username, same for all smb shares
cifspassword: "password" # optional, smb password
```

## Installation

---

The installation of this add-on is pretty straightforward and not different in comparison to installing any other add-on.


1. Install this add-on.
1. Click the `Save` button to store your configuration.
1. Set the add-on options to your preferences
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.
1. Open the webUI and adapt the software options

## Support

Create an issue on github

## Illustration

---

![illustration](https://www.bazarr.media/assets/img/upgrade.png)
