===============================================================================
                        HOME ASSISTANT ADD-ON UPDATER
===============================================================================

Keep your Home Assistant custom add-ons automatically updated with version checks 
and optional notifications. This add-on monitors your repository and updates 
configuration files when new Docker image versions become available.

===============================================================================
INSTALLATION
===============================================================================

1. Add this repository to your Home Assistant add-on store.
2. Install the "Add-on Updater" add-on.
3. Configure it with your GitHub credentials (see CONFIGURATION section).
4. Set up the required automation (example below).

===============================================================================
REQUIRED AUTOMATION (COPY & PASTE INTO AUTOMATIONS)
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
CONFIGURATION OPTIONS (IN options.json)
===============================================================================

[REQUIRED]
github_repo      = "https://github.com/your/repo"
github_username  = "your_github_username"
github_token     = "ghp_yourgithubtoken"

[RECOMMENDED]
timezone         = "America/New_York"
dry_run          = true          # Test mode (no changes will be made)
debug            = false         # Enable verbose logs for troubleshooting

===============================================================================
NOTIFICATION SETUP (OPTIONAL)
===============================================================================

-- GOTIFY --
notification_service  = "gotify"
notification_url      = "https://your.gotify.server"
notification_token    = "your_app_token"

-- NTFY.SH --
notification_service  = "ntfy"
notification_url      = "https://ntfy.sh"
notification_to       = "your_topic_name"

===============================================================================
TROUBLESHOOTING
===============================================================================

AUTOMATION NOT RUNNING?
  - Ensure the add-on ID matches your actual installation.
  - Confirm the automation is enabled in Home Assistant.
  - Check the Home Assistant logs for related errors.

UPDATES NOT DETECTED?
  - Review the add-on logs for API or connectivity issues.
  - Ensure your GitHub token has full repository access.
  - Make sure your Docker images use proper version tags (avoid "latest").

NOTIFICATIONS FAILING?
  - Test your notification service manually outside Home Assistant.
  - Enable `debug = true` to see detailed log output.
  - Verify the notification URL, token, and topic formatting.

===============================================================================
BEST PRACTICES
===============================================================================

1. Start with `dry_run = true` to validate setup without making changes.
2. Configure and test notifications before enabling automatic updates.
3. Schedule update checks during off-peak hours (e.g., 3 AM).
4. Monitor add-on logs regularly, especially after updates or changes.
5. Keep your GitHub token safe and secure.
6. Confirm the add-on ID used in automation matches your actual ID.
7. Manually run the automation once after setup to verify functionality.

===============================================================================
