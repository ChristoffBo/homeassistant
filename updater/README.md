# 🧩 Home Assistant Add-on Updater

Automatically checks for updates to your custom add-ons, compares Docker image versions across registries, updates files, and optionally notifies you.

---

## ✅ Features

- 🔍 Checks for new versions using **Docker Hub**, **GitHub Container Registry**, and **LinuxServer.io**
- 🧠 Detects version from `config.json`, `build.json`, or `updater.json`
- 📝 Updates `version` fields in config/build files
- 📦 Automatically commits changes to GitHub
- 📢 Sends **Gotify** notifications for updates
- 📜 Color-coded logs and dry-run support
- 🛑 One-time execution per run (no infinite loops)
- 🌍 Timezone-aware timestamps

---

## 📁 File Locations

| File | Purpose |
|------|---------|
| `/data/options.json` | Add-on settings from Home Assistant UI |
| `/data/homeassistant` | Cloned GitHub repo with your add-ons |
| `/data/updater.log` | Output log file |
| `/data/updater.lock` | Execution lock file |

---

## ⚙️ Required Configuration (UI or `options.json`)

```json
{
  "repository": "https://github.com/ChristoffBo/homeassistant",
  "gituser": "ChristoffBo",
  "gittoken": "ghp_YourGitHubTokenHere",
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
  "cron": ""
}
```

---

## 🔔 Notification Example

```text
📦 Add-on Update Summary
🕒 2025-08-02 21:55:22 SAST

2fauth:             ✅ Up to date (5.6.0)
gitea:              🔄 1.24.3 → 1.25.0
gotify:             ⚠️ No image defined
heimdall:           ⏭️ Skipped
```

---

## 🧪 Optional Modes

- **Dry Run:** Set `dry_run: true` to simulate updates without changing files
- **Skip Push:** Prevents `git push` after commit (useful for testing)

---

## 🚫 Skipped Add-ons

- `updater` – Prevents self-modification
- `heimdall` – Skipped due to tag issues

---

## 🚀 How It Works

1. Reads config from `options.json`
2. Clones your GitHub repo
3. Loops through each add-on
4. Detects latest tag
5. Compares version and updates files if needed
6. Commits & pushes to GitHub
7. Sends summary via Gotify

---

## 📎 Notes

- Only explicit versioned tags are used (no `latest`)
- Add-ons must have an `image` field in `config.json` or valid `build.json`
- Tags like `dev`, `rc`, or `beta` are ignored
- Script runs once and exits. Use cron or Home Assistant automation to schedule
