Home Assistant Add-on Updater
============================

Automatically checks and updates your custom add-ons when new versions are available.

■ Features
- Checks for new Docker image versions
- Updates add-on configs automatically
- Supports Gotify, ntfy, and Apprise notifications
- Safe dry-run mode for testing

■ Setup Instructions

1. INSTALL THE ADD-ON
- Add this repository to your Home Assistant
- Install the "Add-on Updater" add-on

2. CONFIGURE THE ADD-ON
Set these required options:
- GitHub Repository URL (your add-ons repo)
- GitHub Username 
- GitHub Token (with repo permissions)

Optional settings:
- Timezone (default: UTC)
- Enable dry-run mode for testing
- Set up notifications (see below)

3. NOTIFICATION SETUP
For Gotify:
- Enable notifications
- Service type: gotify
- Server URL: https://your.gotify.server/
- App token: your-gotify-token

For ntfy:
- Enable notifications  
- Service type: ntfy
- Server URL: https://ntfy.sh/
- Topic: your-topic-name

4. CREATE AUTOMATION
Copy and paste this into your Home Assistant automations.yaml or UI editor:

alias: "Check for Add-on Updates"
description: "Daily check for add-on updates"
trigger:
  - platform: time
    at: "03:00:00"
action:
  - service: hassio.addon_restart
    target:
      addon: a0d7b954_updater
mode: single

■ How It Works
1. Daily at 3 AM (adjust time in automation if needed)
2. Restarts the updater add-on
3. Add-on checks all add-ons for updates
4. Updates versions if newer ones exist
5. Sends notifications if configured

■ Troubleshooting
- If updates aren't happening: Check add-on logs
- For GitHub errors: Verify token permissions
- Notification issues: Check server URLs and tokens

■ Recommended
- First run: Enable dry-run mode
- Check logs after installation
- Set notifications for errors