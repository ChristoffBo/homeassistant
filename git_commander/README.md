# Git Commander

**Git Commander** is a Home Assistant add-on that enables you to:
- Upload ZIP files and push them to GitHub or Gitea
- Run Git commands (pull, push, reset, stash, log, etc.)
- Back up your entire `/data` directory

## Tabs
1. **Uploader** – Drop a zip file, select repo type (GitHub/Gitea), auto creates folder and pushes
2. **Toolkit** – Execute raw git commands via dark-mode web UI
3. **Backup** – One-click to zip and download `/data` contents

## Configuration
- Add your full GitHub/Gitea URLs (e.g. https://github.com/username/repo)
- Tokens must have full repo access
- Configurable via UI or `options.json`

## Icons
- `icon.png`, `logo.png` included in root

## Requirements
- Home Assistant OS/Supervisor
- Ingress support enabled
