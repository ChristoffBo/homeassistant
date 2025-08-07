# 🧩 Home Assistant Add-on Updater

Automatically checks for updates to your custom add-ons, compares Docker image versions across registries, updates files, and optionally notifies you.

✅ Features: Checks for new versions using Docker Hub, GitHub Container Registry (GHCR), and LinuxServer.io. Detects version from config.json, build.json, or updater.json. Updates version fields in config/build files. Automatically commits changes to GitHub or Gitea. Sends Gotify notifications for updates. Color-coded logs and dry-run support. One-time execution per run (no infinite loops). Timezone-aware timestamps. Supports skipping specific add-ons via UI (skip_addons). Supports GitHub and Gitea as repo providers. Automatically creates or updates a CHANGELOG.md.

📁 File Locations: /data/options.json — Add-on settings from Home Assistant UI. /data/homeassistant — Cloned repo with your add-ons. /data/updater.log — Output log file.

⚙️ Configuration Example:

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

🔔 Notification Example:

📦 Add-on Update Summary  
🕒 2025-08-07 13:55:22 SAST  
2fauth: ✅ Up to date (5.6.0)  
gitea: 🔄 1.24.3 → 1.25.0  
gotify: ⚠️ No image defined  
heimdall: ⏭️ Skipped  
✅ Git pull succeeded  
✅ Git push succeeded  

Messages may include: ❌ Git pull failed, ⏭️ Git push skipped (skip_push enabled), ℹ️ No changes to commit or push, 🔁 DRY RUN MODE ENABLED

🧪 Optional Modes: dry_run: true — Simulates updates but makes no changes. skip_push: true — Applies updates but does not push. skip_addons — List of folder names to skip.

🚫 Skipped Add-ons: To skip add-ons, list them in skip_addons like ["heimdall", "updater"].

🔀 GitHub and Gitea Setup: Use only one provider at a time. For GitHub, set git_provider to github and provide github_repository, github_username, and github_token. For Gitea, set git_provider to gitea and provide gitea_repository, gitea_username, and gitea_token. Use full HTTPS URLs for all repositories.

🧠 Tag Filtering: Only semantic version tags are used (e.g. 1.2.3, v2.0.1). Tags like latest, rc, dev, beta are ignored. Architecture placeholders like {arch} are automatically resolved.

🚀 How It Works: Loads all settings from /data/options.json. Clones your GitHub or Gitea repo to /data/homeassistant. Iterates over every subfolder. Detects and parses config.json or build.json. Extracts Docker image or build reference. Queries latest tag. Compares with current version. If newer, updates version, updates/creates CHANGELOG.md. Commits and optionally pushes changes. Sends notification if enabled. Logs everything to /data/updater.log. Exits cleanly.

🔄 Scheduling: Use Home Assistant automation or cron to run periodically. This add-on runs once and exits.

✅ Requirements: Add-ons must have a valid config.json or build.json with image or build_from field. A valid GitHub or Gitea repository must be accessible. Gotify notifications are optional but must be configured correctly.

🧠 Notes: Logs written to /data/updater.log. Works with private and public repos. ARM64 and AMD64 supported. Designed for custom Home Assistant add-on repos.

✅ Built For: Automating update checks, changelog tracking, and Git commits for custom Home Assistant add-ons with optional push and notification support. No user interaction required once configured.