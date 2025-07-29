=============================================
HOME ASSISTANT ADD-ON UPDATER
=============================================

Automatically checks and updates your custom add-ons with version tracking and notifications.

■ INSTALLATION
─────────────────────────────────────────────
1. Add this repository to your Home Assistant
2. Install the "Add-on Updater" add-on
3. Configure with your GitHub details below
4. Add the required automation (see below)

■ REQUIRED AUTOMATION (COPY-PASTE READY)
─────────────────────────────────────────────
alias: "Add-on Version Check"
description: "Daily check for add-on updates"
mode: single
trigger:
  - platform: time
    at: "03:00"
condition: []
action:
  - service: hassio.addon_restart
    target:
      addon: a0d7b954_updater
    data: {}

■ CONFIGURATION OPTIONS
─────────────────────────────────────────────
[REQUIRED]
github_repo = "https://github.com/your/repo"
github_username = "your_username"
github_token = "ghp_yourtoken"

[RECOMMENDED]
timezone = "America/New_York"
dry_run = true (for initial testing)
notify_on_error = true

■ NOTIFICATION SETUP
─────────────────────────────────────────────
For Gotify:
notification_service = "gotify"
notification_url = "https://your.gotify.server"
notification_token = "your-app-token"

For ntfy:
notification_service = "ntfy"
notification_url = "https://ntfy.sh"
notification_to = "your_topic"

■ TROUBLESHOOTING
─────────────────────────────────────────────
• Automation not running?
  - Verify addon ID matches yours
  - Check automation is enabled

• Updates not detected?
  - Check add-on logs
  - Verify GitHub token has repo access

• Notifications failing?
  - Test notification service separately
  - Enable debug mode

■ BEST PRACTICES
─────────────────────────────────────────────
• Always start with dry_run enabled
• Set up error notifications first
• Schedule checks during off-peak hours
• Monitor logs after initial setup
• Verify addon ID in Supervisor → Add-ons