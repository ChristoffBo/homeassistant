Home Assistant Addon Updater

A Home Assistant addon script to automatically check and update your Home Assistant addons' Docker image versions by pulling the latest tags from Docker registries.
Supports Docker Hub, LinuxServer.io, and GHCR images.

Features

    Clone or update your addon repository from GitHub (supports private repos with authentication).

    Automatically fetch the latest Docker image tags from:

        Docker Hub (including LinuxServer.io images)

        GitHub Container Registry (GHCR)

    Update config.json and updater.json with the latest Docker image version.

    Maintain and append to a CHANGELOG.md with update details.

    Scheduled update checks daily at a configurable time.

    Support for build.json multi-architecture images.

    Logs progress with colored and emoji-enhanced output.

    Shows DockerHub API rate limit info before each scheduled check.

    Safe retries on DockerHub API calls.

    Skips addons without Docker image definitions.

How to Use

    Configure your addon

Create or update your /data/options.json with the following keys:

{
"github_repo": "https://github.com/yourusername/your-addons-repo.git",
"github_username": "your-github-username", // Optional, for private repos
"github_token": "your-github-personal-access-token", // Optional, for private repos
"dockerhub_token": "your-dockerhub-personal-access-token", // Optional, for DockerHub API rate limit auth
"check_time": "03:00" // Daily check time in HH:MM (24h) format
}

    Start the addon

The script will:

    Clone your repository if not already present.

    Pull the latest updates from GitHub.

    Check each addon folder for Docker image tags.

    Update versions and changelogs if new tags are found.

    Run daily update checks at your specified check_time.

    View logs

Logs show:

    What addons were checked.

    Which addons were updated.

    DockerHub API rate limit remaining.

    Next scheduled check time.

    Optional

    Configure notifications or further customize your addon as needed.

Supported Docker Registries

    Docker Hub (including LinuxServer.io images)

    GitHub Container Registry (GHCR)

    Future support for other registries can be added.

Notes

    The script requires jq and git installed in the addon environment.

    Make sure your GitHub and DockerHub tokens have the necessary permissions.

    Logs are cleared daily at 17:00 to keep output clean.

    Addons without Docker image info are skipped with a notice.

Troubleshooting

    If you get "UNAUTHORIZED" errors querying DockerHub, ensure you have set a valid DockerHub token (dockerhub_token) in your config.

    Check that your GitHub token has repo permissions if your repo is private.

    Verify your check_time is in HH:MM 24-hour format.

    Review addon folder structure; it expects a config.json or build.json file with Docker image info.
