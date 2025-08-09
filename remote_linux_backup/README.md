# Remote Linux Backup (Home Assistant add-on)

Back up and restore remote Linux systems over SSH.

## Features
- **Rsync** (file-level) and **DD** (full disk image)
- **SSH port** selection
- **Bandwidth limit** for rsync
- **Exclude patterns** for rsync
- **Gotify** notifications on completion
- **Scheduler** (cron-style) using APScheduler
- Works with NAS paths you mount into the container (e.g. `/backup`)

## Configuration (`Supervisor → Add-on → Configuration`)
```json
{
  "ui_port": 8066,
  "known_hosts": [],
  "gotify_enabled": false,
  "gotify_url": "",
  "gotify_token": "",
  "auto_install_tools": true,
  "dropbox_enabled": false,
  "dropbox_remote": "dropbox:HA-Backups",
  "nas_mounts": [],
  "server_presets": [],
  "jobs": []
}
