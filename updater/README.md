Home Assistant Addons Docker Version Updater

Overview

This Home Assistant addon monitors your installed addons' Docker image versions, automatically updating their config.json version fields to match the latest available Docker tags on Docker Hub.

It helps keep your addons metadata accurate and provides:

    Automatic updater.json file creation and tracking for each addon

    Colored and clear logs indicating update status (updated in green, up-to-date in blue, warnings in yellow)

    Notifications on updates via Gotify and Mailrise (configurable)

    Daily scheduled update checks at a configurable time (default: 03:00)

    Immediate update check on addon startup

    Displays DockerHub API rate limit info before scheduling next check

    Skips addons that do not specify a Docker image

    Robust DockerHub API call retry logic

Configuration

Configure the addon through the Home Assistant addon options UI or by editing options.json with these settings:

{
"github_repo": "https://github.com/ChristoffBo/homeassistant.git",
"github_username": "",
"github_token": "",
"check_time": "03:00",
"gotify_url": "http://your-gotify-server:port",
"gotify_token": "your-gotify-token",
"mailrise_url": "http://your-mailrise-endpoint"
}

Options:

github_repo - Your GitHub repository URL containing addon sources (optional)
github_username - GitHub username for private repo access (optional)
github_token - GitHub access token for private repo access (optional)
check_time - Daily time to check for addon updates (HH:MM, 24h format), default "03:00"
gotify_url - Gotify server URL for notifications (optional)
gotify_token - Gotify API token (optional)
mailrise_url - Mailrise webhook URL for notifications (optional)

How It Works

    On startup, the addon immediately checks all installed addons under /addons/.

    For each addon, if a config.json exists and contains an .image field, it fetches the latest Docker tag from Docker Hub.

    If the tag differs from the current version field in config.json, it updates config.json and records the update timestamp in updater.json.

    Logs are colored and provide clear status messages.

    Sends notifications via Gotify and Mailrise upon successful updates.

    Displays Docker Hub API rate limits before scheduling the next daily check.

    Then waits, running the check again daily at the configured check_time.

Logging

    Green logs: Addons updated with new Docker tags.

    Blue logs: Addons already up-to-date.

    Yellow warnings: Missing Docker image field, API fetch errors, retry attempts, or notification failures.

Notifications

    Notifications are sent on successful addon updates if Gotify or Mailrise URLs and tokens are configured.

    No notifications are sent if these are not configured.

Requirements & Permissions

    The addon needs read/write access to the /addons/ directory.

    For DockerHub API access, internet connection is required.

    For notifications, network access to Gotify and/or Mailrise servers is required.

    The addon must run with permissions to read/write addon config files and create/update updater.json.

Troubleshooting

    If no updates appear and versions are not changing, verify that your addons’ config.json includes a valid .image field specifying the Docker image.

    Check the addon logs for warnings about missing Docker images or API fetch errors.

    Verify network access to Docker Hub, Gotify, and Mailrise endpoints.

    Check API rate limits logged before the next scheduled run.
