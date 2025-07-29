Home Assistant Add-on Updater
============================

A simple way to keep your custom add-ons automatically updated.

✧ What This Does
- Checks your add-ons for available updates daily
- Updates version numbers in your repository
- Keeps a changelog of all updates
- Optional notifications when updates occur

✓ Requirements
- Home Assistant OS or Supervised
- GitHub repository with your add-ons
- GitHub personal access token with repo permissions

⚙ Installation
1. Add this repository to your Home Assistant add-on store
2. Install the "Add-on Updater" add-on
3. Configure with your GitHub details (see below)
4. Create the automation (copy-paste ready below)

🔧 Configuration Options
[Required]
github_repo = "https://github.com/your/your-repo"
github_username = "your_github_name"
github_token = "ghp_yourtokenhere"

[Optional]
timezone = "America/New_York" 
dry_run = false
debug = false

[Notifications - set all 3]
notifications_enabled = true
notification_service = "gotify" (or "ntfy"/"apprise")
notification_url = "https://your.notification.server"
notification_token = "yourtoken" (for Gotify)

🔄 Required Automation
Copy this exact automation to your Home Assistant:

alias: Update Add-ons Daily
description: Checks for add-on updates at 3 AM
trigger:
  - platform: time
    at: "03:00"
action:
  - service: hassio.addon_restart
    target:
      addon: a0d7b954_updater
mode: single

❗ Important Notes
1. The addon ID (a0d7b954_updater) MUST match what you see in your Home Assistant
2. Time format MUST use quotes around the time
3. Automation must be in single mode

🔍 Checking It Works
1. After setup, check the add-on logs
2. Look for "Starting update check" messages
3. First run may take longer as it clones your repo

🛠 Troubleshooting
If updates aren't happening:
- Verify your GitHub token has repo permissions
- Check the add-on logs for errors
- Make sure the automation is enabled
- Try manually triggering the automation

📅 Recommended Schedule
- Daily checks are best (3 AM shown above)
- Avoid peak usage times
- More frequent checks aren't necessary

📢 Notification Setup Examples
For Gotify:
notification_url = "https://gotify.yourserver.com"
notification_token = "your-app-token"

For ntfy:
notification_url = "https://ntfy.sh"
notification_to = "your_topic_name"
