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
You must create this automation in Home Assistant to check for updates daily:

alias: "Check for Add-on Updates"
trigger:
  - platform: time
    at: "03:00"
action:
  - service: hassio.addon_restart
    target:
      addon: a0d7b954_updater

■ How It Works
1. The add-on checks each add-on's Docker image for updates
2. If updates found:
   - Updates version in config files
   - Updates changelog
   - Commits changes to GitHub
3. Sends notifications if configured

■ Troubleshooting
- GitHub errors: Check your token has repo access
- Notifications not working: Verify server URL and tokens
- No updates found: Check your add-ons have proper image tags

■ Tips  
- Start with dry-run enabled
- Check logs after first run
- Daily checks are recommended