🧩 Home Assistant Add-on Updater
Self-contained update automation tool for custom Home Assistant add-ons. Compares Docker image tags across registries, updates version fields in config/build files, commits to Git, and optionally sends notifications.

✅ Compares versions via Docker Hub, GHCR, and lscr.io
✅ Supports config.json, build.json, and updater.json
✅ Automatically updates version fields and CHANGELOG.md
✅ Pushes to GitHub or Gitea with token auth
✅ Sends optional Gotify notifications
✅ Logs all actions with color-coded output
✅ Supports dry run, skip push, and skip add-ons
✅ Timezone-aware timestamps
✅ Exits cleanly after one run

📁 Files:

/data/options.json — add-on settings

/data/homeassistant — cloned add-on Git repo

/data/updater.log — full log output


⚙️ Configuration:
{
"timezone": "Africa/Johannesburg",
"dry_run": false,
"skip_push": false,
"debug": true,
"enable_notifications": true,
"notification_service": "gotify",
"notification_url": "http://your-gotify-url:port",
"notification_token": "gotify-app-token",
"notification_to": "",
"notify_on_success": true,
"notify_on_error": true,
"notify_on_updates": true,
"skip_addons": ["heimdall", "updater"],
"git_provider": "github",
"github_repository": "https://github.com/YourUser/homeassistant",
"github_username": "YourUser",
"github_token": "ghp_xxx",
"gitea_repository": "",
"gitea_username": "",
"gitea_token": ""
}

🧪 Options:
timezone — sets timezone for logs and notifications
dry_run — true to simulate update checks only
skip_push — true to avoid pushing changes to Git
debug — enables verbose logging
enable_notifications — true to enable notification sending
notification_service — currently only "gotify" supported
notification_url — full URL of Gotify server
notification_token — Gotify application token
notification_to — optional future use
notify_on_success — notify on successful runs
notify_on_error — notify on failure
notify_on_updates — notify only if updates occurred
skip_addons — list of add-on folder names to exclude
git_provider — "github" or "gitea"
github_repository — full HTTPS URL to GitHub repo
github_username — GitHub username
github_token — GitHub token
gitea_repository — full HTTPS URL to Gitea repo
gitea_username — Gitea username
gitea_token — Gitea token

🌍 How to use:
Runs once per execution. Loads config from /data/options.json, clones the repo to /data/homeassistant, scans each add-on folder, parses config/build/updater JSON, extracts image, checks registries for latest semantic tag, compares with current version, updates JSON file and CHANGELOG.md if needed, commits and optionally pushes. Sends notification if enabled and writes full log to /data/updater.log.

🧠 Semantic versioning enforced. Tags like 1.2.3 or v2.1.0 allowed. Tags like latest, rc, dev, beta are ignored. {arch} values in image tags are resolved automatically.

🔁 Schedule the add-on via Home Assistant automation or external cron. It runs once and exits.

🧠 Fully self-hosted and automatic. Once configured, requires no user input.

