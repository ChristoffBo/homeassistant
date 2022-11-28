# OpenVPN Client Add-On

This is a Add-On for [Home Assistant](https://www.home-assistant.io) which enables to tunnel the communication of your Home Assistant server with the world through a VPN connection.

## Installation

Move your client.ovpn file to /share folder on your server.
Create a file in /share folder called auth.txt and add your username and password on the first and second line.
edit your ovpn file and add the following auth-user-pass /share/auth.txt

Click on OpenVPN Client, then INSTALL and Start.
