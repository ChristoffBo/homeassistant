
# Home assistant add-on: Prowlarr

- Latest version : https://github.com/alexbelgium/hassio-addons

## About

---

[Prowlarr](https://github.com/Prowlarr/Prowlarr) is an indexer manager/proxy built on the popular arr .net/reactjs base stack to integrate with your various PVR apps.
This addon is based on the docker image https://github.com/linuxserver/docker-prowlarr

## Installation

---

The installation of this add-on is pretty straightforward and not different in comparison to installing any other add-on.


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

