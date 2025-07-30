n8n - Workflow Automation Add-on for Home Assistant

n8n is an open-source, node-based workflow automation tool. This Home Assistant add-on runs the official 'n8nio/n8n' container, allowing you to create automated workflows between services directly from your Home Assistant environment.

FEATURES
--------
- Uses official n8nio/n8n Docker image
- Workflow builder in your browser
- Persistent workflows and credentials
- Optional Basic Auth login
- Configurable timezone

CONFIGURATION OPTIONS
---------------------
Set these options in the add-on GUI:

timezone:     Your timezone (example: Europe/London)
auth_user:    Username for Basic Auth login (optional)
auth_pass:    Password for Basic Auth login (optional)

Note: Leave both auth_user and auth_pass blank to disable authentication.

ACCESSING N8N
-------------
Once the add-on is running, open this in your browser:

http://homeassistant.local:5678
or
http://<your-ha-ip>:5678

DATA STORAGE
------------
All workflows and settings are saved to /data inside Home Assistant's add-on container storage.

RESOURCES
---------
n8n documentation: https://docs.n8n.io
n8n homepage:      https://n8n.io