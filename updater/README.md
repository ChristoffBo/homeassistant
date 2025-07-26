Home Assistant Addons Docker Version Updater
Overview

This Home Assistant addon monitors your installed addons' Docker image versions, automatically updating their config.json version fields to match the latest available Docker tags.

It supports fetching the latest Docker tags from multiple container registries including:

    Docker Hub (default)

    linuxserver.io Docker registry

    GitHub Container Registry (GHCR)

This ensures accurate version tracking for addons regardless of where their Docker images are hosted.

The addon provides:

    Automatic creation and update of updater.json files per addon

    Clear, colored logs with update status (green for updated, blue for up-to-date, yellow for warnings)

    Notifications via Gotify and Mailrise (optional and configurable)

    Scheduled daily update checks at a configurable time (default: 03:00)

    Immediate update check on addon startup

    DockerHub API retry/backoff on rate limits or failures

    Skips addons that do not specify a Docker image

    Shows DockerHub API rate limit info before scheduling next run

Configuration

Configure via the Home Assistant addon options or by editing options.json:

{
  "github_repo": "https://github.com/ChristoffBo/homeassistant.git",
  "github_username": "",
  "github_token": "",
  "check_time": "03:00",
  "gotify_url": "http://your-gotify-server:port",
  "gotify_token": "your-gotify-token",
  "mailrise_url": "http://your-mailrise-endpoint"
}

Option	Description	Required	Default
github_repo	Your GitHub repository URL containing addon sources	No	As above
github_username	GitHub username for private repo access (optional)	No	Empty
github_token	GitHub access token for private repo access (optional)	No	Empty
check_time	Daily time to check for addon updates (HH:MM, 24h format)	No	03:00
gotify_url	Gotify server URL for notifications	No	Empty
gotify_token	Gotify API token	No	Empty
mailrise_url	Mailrise webhook URL for notifications	No	Empty
How It Works

    On startup, the addon immediately scans all installed addons in /addons/.

    For each addon with a config.json file containing an .image field, it detects the container registry hosting the image and fetches the latest Docker tag accordingly:

        Docker Hub (default registry)

        linuxserver.io Docker Hub registry

        GitHub Container Registry (ghcr.io)

    If the latest Docker tag differs from the version in config.json, it updates the version and records the update time in updater.json.

    Adds missing updater.json files automatically for addons with Docker images.

    Logs updates with color-coded output and status messages.

    Sends notifications via Gotify and Mailrise if configured.

    Shows DockerHub API rate limits before scheduling the next daily check.

    Waits and repeats daily checks at the configured check_time.

Logging

    Green: Addons updated to a new Docker tag.

    Blue: Addons already up-to-date.

    Yellow: Warnings including missing Docker image fields, API fetch errors, retries, or notification failures.

Notifications

    Notifications are sent on successful addon updates if Gotify or Mailrise URLs and tokens are configured.

    No notifications if not configured.

Requirements & Permissions

    Requires read/write access to the /addons/ directory.

    Internet access to Docker Hub, linuxserver.io, GitHub Container Registry, Gotify, and/or Mailrise as applicable.

    Permissions to create and update addon config files and updater.json.

Troubleshooting

    Ensure addons' config.json includes a valid .image field specifying the Docker image.

    Check logs for warnings about missing images or API errors.

    Confirm network connectivity to Docker registries and notification endpoints.

    Review API rate limit info logged before next scheduled run.
