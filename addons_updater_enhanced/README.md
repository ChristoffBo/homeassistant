This is an enhanced version of alexbelgium's Home Assistant addon updater with support for both GitHub and Gitea repositories, plus optional Gotify notifications.

BASIC CONFIGURATION

Add these required options to your options.json:
{
"repo_source": "github",
"repo_path": "/config/addons",
"addon_paths": ["addons"],
"update_mode": "commit"
}

FULL CONFIGURATION OPTIONS

{
"repo_source": "github",
"enable_gotify": false,
"gotify_url": null,
"gotify_token": null,
"gitea_api_url": null,
"gitea_token": null,
"repo_path": "/config/addons",
"repo_branch": "main",
"addon_paths": ["addons", "community"],
"update_mode": "commit",
"timeout": 300,
"log_level": "info",
"validate_ssl": true
}

REQUIREMENTS

    Each addon must have:

        A config.json file

        An upstream_repo defined (e.g. "user/repo")

    For Gitea support:

        Set repo_source to "gitea"

        Provide gitea_api_url and gitea_token

    For Gotify notifications:

        Set enable_gotify to true

        Provide gotify_url and gotify_token

HOW IT WORKS

    Scans your specified addon directories

    Checks the latest version from GitHub/Gitea

    Updates config.json if newer version exists

    Commits changes (can optionally push)

    Sends notifications if enabled

LOGGING

    Console output

    /var/log/addons-updater.log

    Gotify notifications (if enabled)

CREDITS

Based on the original by alexbelgium:
https://github.com/alexbelgium/hassio-addons
