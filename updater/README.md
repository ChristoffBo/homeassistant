================================================================================
                         HOME ASSISTANT ADD-ON UPDATER
================================================================================

Automatically keep your custom Home Assistant add-ons up to date with version checks 
and optional notifications. This add-on monitors your repository and updates config 
files when new versions of Docker images are available.

================================================================================
INSTALLATION
================================================================================

1. Add this repository to your Home Assistant add-on store.
2. Install the "Add-on Updater" add-on.
3. Configure it with your GitHub credentials (see below).
4. Set up the required automation (see example below).

================================================================================
REQUIRED AUTOMATION (COPY & PASTE)
================================================================================

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

================================================================================
CONFIGURATION OPTIONS
================================================================================

[REQUIRED]
github_repo       = "https://github.com/your/repo"
github_username   = "your_github_username"
github_token      = "ghp_yourgithubtoken"

[RECOMMENDED]
timezone          = "America/New_York"
dry_run           = true          # Test mode - no changes made
debug             = false         # Enable for detailed logs

================================================================================
NOTIFICATION SETUP (OPTIONAL)
================================================================================

[Gotify]
notification_service  = "gotify"
notification_url      = "https://your.gotify.server"
notification_token    = "your_app_token"

[Ntfy]
notification_service  = "ntfy"
notification_url      = "https://ntfy.sh"
notification_to       = "your_topic_name"

================================================================================
TROUBLESHOOTING
================================================================================

AUTOMATION NOT RUNNING?
- Make sure the add-on ID is correct (check in Supervisor).
- Confirm the automation is enabled in Settings > Automations.
- Review Home Assistant logs for related errors.

UPDATES NOT DETECTED?
- Check add-on logs for connectivity or parsing issues.
- Ensure GitHub token has access to the repository.
- Verify Docker images use versioned tags (not just "latest").

NOTIFICATIONS FAILING?
- Test your notification service independently first.
- Enable `debug = true` for more detailed logs.
- Confirm notification URL, token, and topic formatting.

================================================================================
BEST PRACTICES
================================================================================

1. Start with `dry_run = true` to safely test behavior.
2. Set up error notifications before enabling full automation.
3. Schedule update checks during off-peak hours (e.g., 3 AM).
4. Review logs regularly, especially after updates or changes.
5. Keep your GitHub token private and secure.
6. Ensure the add-on ID matches your actual installation.
7. Manually trigger automation after setup to verify.

================================================================================
