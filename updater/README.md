Home Assistant Add-on Updater

This is a Home Assistant add-on script that automatically checks and updates your custom add-on Docker image versions. It fetches the latest version tags from Docker Hub, LinuxServer.io, or GitHub Container Registry (GHCR) and updates your add-ons accordingly.
🔧 Features

    ✅ Pulls or clones your GitHub repo (supports private repos with credentials).

    📦 Checks Docker image versions from:

        Docker Hub

        LinuxServer.io

        GHCR (GitHub Container Registry)

    🧠 Compares tags by version number only (ignores latest, architecture prefixes, or date-based tags).

    ✏️ Updates:

        config.json

        build.json (if present)

        updater.json

    📝 Creates or appends to CHANGELOG.md with:

        Add-on name

        Old vs. new version

        Docker image used

        Link to Docker Hub or GHCR image

    🕒 Respects a configurable daily cron time (set via GUI).

    🌍 Timezone-aware using your selected Home Assistant timezone.

    🎨 Clean, color-coded log output with emojis.

    📩 Optional notifications via:

        Gotify

        Apprise

        Mailrise

        (Only sent when something is updated or created)

    🛠 Safe retry for DockerHub API (resilient to rate limits or downtime).

    🚫 Skips add-ons without a defined image.

    🧹 Clears logs daily at 17:00 for cleanliness.

    📅 Prints next cron execution time at the end of each run.

⚙️ How to Set Up

In the Home Assistant add-on GUI, configure the options:

{
  "github_repo": "https://github.com/yourusername/your-addons-repo.git",
  "github_username": "your-github-username",              // Optional, for private repos
  "github_token": "your-github-personal-access-token",    // Optional, for private repos
  "dockerhub_token": "your-dockerhub-token",              // Optional, to avoid rate limit
  "check_time": "03:00",                                  // Daily check time (24h format)
  "gotify_url": "http://your-gotify-url/message",         // Optional
  "gotify_token": "your-gotify-token",                    // Optional
  "apprise_url": "discord://token/serverid",              // Optional
  "mailrise_url": "http://mailrise:5000/email@example.com"// Optional
}

Then start the add-on.
🚀 What Happens

    Pulls the latest from your GitHub repo.

    Scans each add-on folder:

        Finds the Docker image.

        Gets the latest version tag.

        Compares with current.

        If a newer version is found:

            Updates config.json, build.json, updater.json

            Adds/updates CHANGELOG.md

            Commits and pushes the changes.

            Sends a notification (if enabled).

    Runs again daily at your defined check_time.

📜 Logs Show:

    ✅ Each add-on's name, current version, and updated version.

    🆕 Any files created or updated.

    📦 API rate limit info from DockerHub.

    🗓️ The next scheduled check time (Day, Hour, Minute).

    ⚠️ Any errors (like image not found or GitHub push failure).

🔔 Notifications

If enabled, you will receive a notification only if something was created or updated, including:

    Add-on name

    New version

    Files touched

    Docker image link

🐳 Supported Registries

    Docker Hub

    LinuxServer.io

    GitHub Container Registry (GHCR)

🧪 Requirements

    jq and git must be installed in the container (already included).

    GitHub token (if private repo) must have repo access.

    DockerHub token (optional but helps avoid rate limits).

❗ Troubleshooting

    UNAUTHORIZED from Docker Hub? → Check dockerhub_token

    Private repo issues? → Use github_token and github_username

    No updates showing? → Ensure correct image name in config.json

    Logs not showing? → Wait for the scheduled check_time or restart the add-on.
