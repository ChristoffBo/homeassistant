===============================================================================
                     HOME ASSISTANT ADD-ON UPDATER
===============================================================================

Keep your custom add-ons automatically updated with version checking and optional
notifications. This add-on monitors your repository and updates configuration
files when new versions are available.

===============================================================================
INSTALLATION
===============================================================================

1. Add this repository to your Home Assistant add-on store
2. Install the "Add-on Updater" add-on
3. Configure with your GitHub credentials
4. Set up the required automation (see below)

===============================================================================
REQUIRED AUTOMATION (COPY-PASTE READY)
===============================================================================

alias: "Add-on Version Check"
description: "Daily check for add-on updates at 3 AM"
mode: single
trigger:
  - platform: time
    at: "03:00"
condition: []
action:
  - service: hassio.addon_restart
    target:
      addon: a0d7b954_updater

===============================================================================
CONFIGURATION OPTIONS
===============================================================================

[REQUIRED SETTINGS]
github_repo      = "https://github.com/your/repo"
github_username  = "your_github_username"
github_token     = "ghp_yourgithubtoken"

[RECOMMENDED SETTINGS]
timezone         = "America/New_York"
dry_run          = true    # Enable for initial testing
debug            = false

===============================================================================
NOTIFICATION SETUP
===============================================================================

[FOR GOTIFY]
notification_service = "gotify"
notification_url    = "https://your.gotify.server"
notification_token  = "your_app_token"

[FOR NTFY]
notification_service = "ntfy"
notification_url    = "https://ntfy.sh"
notification_to     = "your_topic_name"

===============================================================================
TROUBLESHOOTING
===============================================================================

* Automation not running?
  - Verify the addon ID matches yours (check in Supervisor)
  - Check the automation is enabled in Settings > Automations
  - View Home Assistant logs for errors

* Updates not detected?
  - Check the add-on logs for connection issues
  - Verify GitHub token has proper repo permissions
  - Ensure your Docker images have version tags

* Notifications failing?
  - Test your notification service separately first
  - Enable debug mode for detailed error logs
  - Double-check URL and token formatting

===============================================================================
BEST PRACTICES
===============================================================================

1. Always start with dry_run enabled to test
2. Configure error notifications before enabling updates
3. Schedule checks during off-peak hours (e.g., 3 AM)
4. Monitor logs closely after initial setup
5. Keep your GitHub token secure
6. Verify addon ID matches your installation
7. Test the automation manually after setup

===============================================================================