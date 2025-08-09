Under Construction

🧩 Remote Linux Backup — Home Assistant Add-on

Full-featured backup and restore tool for remote Linux systems over SSH. Supports full disk imaging (dd), rsync folder backups, ZFS, NAS mounts, and cloud uploads. Designed for non-technical users with an easy-to-use web UI, preset manager, and file explorer.

✅ Debian-based for maximum compatibility
✅ Web UI with dark mode and easy navigation
✅ Backup **from** or **to** multiple servers, NAS shares, or cloud targets
✅ Supports full (entire machine) backups or file/folder selection
✅ Built-in mount manager for SMB/CIFS, NFS, and local paths
✅ Restore mode with source selection and overwrite protection
✅ Bandwidth limits, progress bars, and backup logs
✅ Gotify notifications for job results (configurable)
✅ Persistent settings stored in `/config`
✅ Alpha-stage: new features actively being added

📁 Files:
- `/data/options.json` — add-on settings
- `/app/www` — web UI files
- `/app/api.py` — main backend API logic
- `/app/scheduler.py` — backup scheduler logic
- `/app/job_runner.py` — executes backup and restore jobs
- `/mnt/mounts` — mounted NAS/cloud drives

⚙️ Configuration:
{
  "port": 8066,
  "mounts": [],
  "backups": [],
  "restores": [],
  "gotify_url": "",
  "gotify_token": "",
  "timezone": "Africa/Johannesburg"
}

🧪 Options:
- `port` — Web UI port (Ingress also available)
- `mounts` — list of SMB/NFS/local mounts (managed in UI)
- `backups` — list of backup presets (managed in UI)
- `restores` — list of restore presets (managed in UI)
- `gotify_url` — full Gotify server URL for notifications
- `gotify_token` — Gotify app token for sending messages
- `timezone` — sets container timezone

🌍 Web UI access:
- Via Home Assistant Ingress (no port needed)
- Or `http://[HOST]:[PORT:8066]` if direct access enabled

🧠 Notes:
- SMB/CIFS and NFS mounts are handled by the built-in Mount Manager.
- File explorer is available for selecting backup/restore paths on mounted shares or remote SSH hosts.
- Full disk backups use `dd` with compression (pigz) for speed.
- Incremental backups use `rsync` for efficiency.

⚠️ Alpha Disclaimer:
This add-on is in **alpha stage**. While it is functional, it is under active development. **If it breaks anything, the user is solely responsible.** Always test on non-critical systems before production use.

👤 Author: Christoff — https://github.com/ChristoffBo

🧾 Sources:
- Debian Base Image — https://github.com/hassio-addons/addon-debian-base
- rsync — https://rsync.samba.org
- pigz — https://zlib.net/pigz/
