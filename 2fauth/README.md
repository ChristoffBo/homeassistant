Home Assistant Add-on: 2FAuth

A web app to manage your Two-Factor Authentication (2FA) accounts and generate their security codes.

About
-----
2FAuth is a self-hosted web application for managing TOTP-based 2FA accounts. This add-on runs the official Docker image of 2FAuth inside Home Assistant using a wrapper add-on.

Features
--------
- Self-hosted 2FA manager
- Web UI accessible via port 8001
- Secure environment configuration
- Email notification support
- Persistent data storage

Installation
------------
1. Add this repository to your Home Assistant add-on store:
   https://github.com/ChristoffBo/homeassistant

2. Install the 2FAuth add-on from the list.

3. Configure the email and app settings in the Supervisor add-on GUI.

4. Start the add-on and access the web UI at:
   https://[YOUR_HOME_ASSISTANT_IP]:8001

Configuration
-------------
The following options are available in the add-on settings (GUI-configurable):

APP_URL: https://auth.bothmainc.com
MAIL_ENCRYPTION: false
MAIL_FROM_ADDRESS: 2fa@notifications.co.za
MAIL_FROM_NAME: 2Fauth
MAIL_HOST: 10.0.0.99
MAIL_MAILER: smtp
MAIL_PORT: 8025
PGID: 0
PUID: 0
TZ: Africa/Johannesburg

Data Persistence
----------------
All 2FAuth data is stored in:
  /data

This maps to /DATA/AppData/2fauth/data on the host.

Security Notes
--------------
- The container runs in privileged mode to enable Docker usage inside the add-on.
- Make sure your Home Assistant instance is secured (e.g., HTTPS, firewall).

Support
-------
This add-on was created for private use by Christoff (https://github.com/ChristoffBo). Contributions, improvements, and feedback are welcome.

Credits
-------
- 2FAuth by @bubka: https://github.com/bubka/2fauth
- Docker image: 2fauth/2fauth:latest
- Home Assistant Add-on Base: ghcr.io/hassio-addons/base