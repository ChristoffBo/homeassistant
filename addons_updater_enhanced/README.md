text

# Addons Updater Enhanced

Enhanced version of alexbelgium's Home Assistant Addon Updater with GitHub/Gitea support and optional Gotify notifications.

## How It Works

1. Scans specified directories for addons
2. Compares local versions against GitHub/Gitea releases
3. Updates config.json and VERSION files when newer versions are found
4. Optionally sends notifications via Gotify

## Basic Configuration (options.json)

```json
{
  "repo_source": "github",
  "repo_path": "/config/addons",
  "addon_paths": ["addons", "community"],
  "update_mode": "commit"
}

Full Configuration Options

Required:

    repo_source: "github" or "gitea"

    repo_path: Path to your addons repository (e.g. "/config/addons")

    addon_paths: List of directories to scan (e.g. ["addons", "community"])

Optional:

    enable_gotify: true/false (default: false)

    gotify_url: Your Gotify server URL

    gotify_token: Your Gotify app token

    gitea_api_url: Required if using Gitea (e.g. "https://your-gitea.com/api/v1")

    gitea_token: Required if using Gitea

    update_mode: "commit" (default) or "push"

    timeout: API timeout in seconds (default: 300)

    log_level: "debug", "info", "warning", or "error" (default: "info")

    validate_ssl: true/false (default: true)

Setup Instructions

    Install via Home Assistant Supervisor

    Configure options.json (see examples above)

    For Gitea:

        Provide gitea_api_url and gitea_token

    For Gotify:

        Set enable_gotify: true

        Provide gotify_url and gotify_token

    Run manually or set up automation

Key Features

    Supports both GitHub and self-hosted Gitea

    Optional Gotify notifications

    Dry-run mode available

    Detailed logging to /var/log/addons-updater.log

    Health checks and error handling

Credits

Based on the original work by alexbelgium:
https://github.com/alexbelgium/hassio-addons/tree/master/addons_updater
