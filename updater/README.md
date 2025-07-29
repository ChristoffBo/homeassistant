Home Assistant Add-on Updater

Created by ChristoffBo with help from ChatGPT and Deepseek AI.

This add-on automatically checks and updates Docker image versions used in your custom Home Assistant add-ons. It compares the current image version with the latest available from Docker Hub, LinuxServer.io, or GitHub Container Registry and updates your add-on metadata if needed.


---

How It Works

Checks your GitHub repo for Home Assistant add-ons.

Compares current Docker image versions with the latest available.

If a new version is found:

Updates config.json an build.json.

Creates or updates CHANGELOG.md.

Optionally pushes changes to GitHub.

Sends a notification (if enabled).


Scheduled by HomeAssistant Please Create an Automation.



---

Main Features

Supports Docker Hub, LinuxServer.io, and GHCR.

Ignores latest, architecture-prefixed, or date-based tags.

Logs everything with timestamps in your configured timezone.

Uses a lock file to avoid running twice at the same time.

Sends optional notifications via Gotify.

GitHub integration with optional push support.

Supports dry run mode for testing.



---

Folder Structure

Your custom add-ons should be inside this path:

https://github.com/YourUser/YourRepo


---

Add-on Configuration (via GUI)

Example settings to paste in the add-on configuration tab in Home Assistant:

{
  "github_repo": "https://github.com/YourUser/YourRepo",
  "github_username": "YourGitHubUsername",
  "github_token": "YourGitHubToken",
  "timezone": "Africa/Johannesburg",
  "max_log_lines": 1000,
  "dry_run": false,
  "skip_push": false,
  "notifications_enabled": true,
  "notification_service": "gotify",
  "notification_url": "https://gotify.example.com",
  "notification_token": "your_token_here",
  "notification_to": "",
  "notify_on_success": true,
  "notify_on_error": true,
  "notify_on_updates": true
}


---

Notifications

If enabled, the add-on will send notifications.
Supported services:

Gotify

---

Logging

Log file: /data/updater.log

Rotates when large

Timestamped in your timezone

Shows what was checked and what was updated



---

Changelog

Each add-on will get a CHANGELOG.md file (or update the existing one) showing:

Version update

Time of update

Image used



---

GitHub Support

If GitHub credentials are added:

Repo is cloned or pulled

Changes are committed and pushed (unless skip_push is true)



---

Advanced Options

dry_run: simulate update without making changes

skip_push: update files locally but don’t push to GitHub

---

Created by ChristoffBo
With help from ChatGPT and Deepseek AI


---


