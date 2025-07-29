Home Assistant Add-on Updater
────────────────────────────

Keep your custom add-ons automatically updated with version checking and notifications.

────────────────────────────
SETUP INSTRUCTIONS
────────────────────────────

1. INSTALL THE ADD-ON
   • Add this repository to your Home Assistant
   • Install the "Add-on Updater" add-on
   • Configure with your GitHub details

2. REQUIRED AUTOMATION
Copy this exact automation to your Home Assistant configuration:

alias: "Add-on Updater Daily Check"
description: "Restarts updater add-on to check for updates daily at 3 AM"
mode: single
trigger:
  - platform: time
    at: "03:00:00"
condition: []
action:
  - service: hassio.addon_restart
    target:
      addon: a0d7b954_updater
    data: {}

3. VERIFICATION
   • Check add-on logs after first run
   • Look for "Starting update check" message
   • Manually trigger automation to test

────────────────────────────
CONFIGURATION OPTIONS
────────────────────────────

REQUIRED SETTINGS:
• github_repo: Your repository URL
• github_username: Your GitHub username  
• github_token: Personal access token with repo scope

OPTIONAL SETTINGS:
• timezone: Your local timezone
• dry_run: Test mode (true/false)
• debug: Verbose logging (true/false)

NOTIFICATION SETUP:
• Enable in add-on configuration
• Choose service (Gotify/ntfy/Apprise)
• Configure URL and credentials

────────────────────────────
TROUBLESHOOTING
────────────────────────────

AUTOMATION NOT WORKING?
• Verify addon ID matches yours
• Check automation is enabled
• Look for errors in Home Assistant logs

UPDATES NOT DETECTED?
• Check add-on logs
• Verify GitHub token permissions
• Ensure Docker images have version tags

NOTIFICATIONS NOT SENDING?
• Check notification service is online
• Verify credentials are correct
• Enable debug mode for more details

────────────────────────────
BEST PRACTICES
────────────────────────────
✓ Start with dry_run enabled
✓ Set notifications for errors
✓ Check logs regularly
✓ Schedule during off-peak hours