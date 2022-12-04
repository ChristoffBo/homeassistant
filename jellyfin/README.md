# Home assistant add-on: jellyfin


## About

[jellyfin](https://jellyfin.media/) organizes video, music, live TV, and photos from personal media libraries and streams them to smart TVs, streaming boxes and mobile devices. This container is packaged as a standalone jellyfin Media Server.

This addon is based on the [docker image](https://github.com/linuxserver/docker-jellyfin) from linuxserver.io.

## Configuration

Webui can be found at `<your-ip>:8096`.

```yaml
PGID: user
GPID: user
TZ: timezone
localdisks: sda1 #put the hardware name of your drive to mount separated by commas, or its label. Ex: sda1, sdb1, MYNAS...
networkdisks: "//SERVER/SHARE" # optional, list of smb servers to mount, separated by commas
cifsusername: "username" # optional, smb username, same for all smb shares
cifspassword: "password" # optional, smb password
cifsdomain: "domain" # optional, allow setting the domain for the smb share
DOCKER_MODS: linuxserver/mods:jellyfin-opencl-intel|linuxserver/mods:jellyfin-amd|linuxserver/mods:jellyfin-rffmpeg # Install graphic drivers
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

[repository]: https://github.com/alexbelgium/hassio-addons
