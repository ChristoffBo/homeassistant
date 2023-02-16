![Logo ](https://github.com/ChristoffBo/homeassistant/blob/main/publicfolders/logo.png)
# Home assistant add-on: Public Folders

- Latest version : https://github.com/Rusketh/RuskethsHomeAddons

## About


 
 By default files under the HA media directory will be served on HTTP port 8080.
http://<HA-IP>:<port>/<handle>/<filepath>

e.g: http://<HA-IP>:8080/media/doorbell/ringtone.mp3

You can change the port and add/remove public directories via the config folder.
Under Config/Options you will find a list called folders, keep in mind Public Folders can only serve files that exist with in the media directory.

folders:
  - media:/media
Where media is the handle and /media is the directory. The handle acts like a folder name with in the URL. I suck at explaining things so here is an example.

If I wanted to create a URL to host my doorbell files I could use the following folder configuration:

folders:
  - door:/media/doorbell
I could then access my ringtone.mp3 from
http://<HA-IP>:8080/door/ringtone.mp3
 

