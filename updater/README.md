# 🧩 Home Assistant Add-on Updater

Automatically checks for updates to your custom add-ons, compares Docker image versions across registries, updates files, and optionally notifies you.

---

## ✅ Features

- 🔍 Checks for new versions using Docker Hub, GitHub Container Registry (GHCR), and LinuxServer.io
- 🧠 Detects version from `config.json`, `build.json`, or `updater.json`
- 📝 Updates version fields in config/build files
- 📦 Automatically commits changes to GitHub or Gitea
- 📢 Sends Gotify notifications for updates
- 📜 Color-coded logs and dry-run support
- 🛑 One-time execution per run (no infinite loops)
- 🌍 Timezone-aware timestamps
- 🔁 Supports skipping specific add-ons via UI (`skip_addons`)
- 🔀 Supports GitHub and Gitea as repo providers

---

## 📁 File Locations

| File                     | Purpose                                |
|--------------------------|----------------------------------------|
| `/data/options.json`     | Add-on settings from Home Assistant UI |
| `/data/homeassistant`    | Cloned repo with your add-ons          |
| `/data/updater.log`      | Output log file                        |

---

## ⚙️ Configuration (`options.json` or UI)

```
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
  "skip_addons": ["heimdall"],
  "git_provider": "github",
  "github_repository": "https://github.com/YourUser/homeassistant",
  "github_username": "YourUser",
  "github_token": "ghp_xxx",
  "gitea_repository": "",
  "gitea_username": "",
  "gitea_token": ""
}
```

---

## 🔔 Notification Example

```
📦 Add-on Update Summary
🕒 2025-08-02 21:55:22 SAST

2fauth:             ✅ Up to date (5.6.0)
gitea:              🔄 1.24.3 → 1.25.0
gotify:             ⚠️ No image defined
heimdall:           ⏭️ Skipped
```

---

## 🧪 Optional Modes

- `dry_run: true` → Simulate updates, no file changes
- `skip_push: true` → Skip pushing changes to remote Git

---

## 🚫 Skipped Add-ons

- `updater` – Prevents self-modification
- Add any add-on name to `skip_addons` in options to exclude

---

## 🚀 How It Works

1. Reads config from `options.json`
2. Clones the GitHub or Gitea repo
3. Loops through each add-on directory
4. Detects latest Docker tag
5. Compares with current version
6. If needed, updates version in `config.json` / `build.json`
7. Commits and optionally pushes changes
8. Sends update summary via Gotify

---

## 📎 Notes

- Only **versioned tags** are used (e.g. `v1.2.3`, no `latest`)
- Tags like `dev`, `rc`, or `beta` are ignored
- Add-ons **must** have a valid image or build config
- This add-on **runs once and exits**
  - Use Home Assistant automation or cron to schedule it
