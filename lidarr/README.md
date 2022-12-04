# Home assistant add-on: Lidarr

- Latest version : https://github.com/alexbelgium/hassio-addons

## About

---

[Lidarr](https://lidarr.audio/) is a music collection manager for Usenet and BitTorrent users. It can monitor multiple RSS feeds for new albums from your favorite artists and will interface with clients and indexers to grab, sort, and rename them. It can also be configured to automatically upgrade the quality of existing files in the library when a better quality format becomes available.
This addon is based on the docker image https://github.com/linuxserver/docker-lidarr

## Installation

---

The installation of this add-on is pretty straightforward and not different in comparison to installing any other add-on.

1. Add my add-ons repository to your home assistant instance (in supervisor addons store at top right, or click button below if you have configured my HA)
   [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Falexbelgium%2Fhassio-addons)
1. Install this add-on.
1. Click the `Save` button to store your configuration.
1. Set the add-on options to your preferences
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.
1. Open the webUI and adapt the software options

## Configuration

---

Webui can be found at <http://your-ip:PORT>.
The default username/password : described in the startup log.
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

## Support

Create an issue on github

## Illustration

---

![illustration](https://www.geekzone.fr/wp-content/uploads/2018/05/lidarr_1.png)

[repository]: https://github.com/alexbelgium/hassio-addons
