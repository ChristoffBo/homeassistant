# ⚠️ Alpha Build Disclaimer

This is an **ALPHA** build. **No assistance will be given.** **No responsibility is accepted for breakage or loss of data.** **Use at your own risk.**

# 🧩 Remote Linux Backup
A full backup & restore solution for remote Linux/UNIX systems with a clean, easy UI. Works over SSH with no command line required. Copy (rsync) for files and folders, or Full Image (dd) for entire disks. Includes a backup browser (download/delete), scheduler (daily/weekly/monthly), connections manager, and optional Gotify notifications. Clear logs and live progress with percent and size. Backups are stored as plain files/folders so they are restorable even without this add-on.

✅ Features: Copy backups via rsync over SSH. Full disk image backups via dd to .img.gz with progress. Restore rsync folders to any path. Restore images to devices with confirmation. File pickers using SFTP to browse remote servers. Saved connections with password storage option. Backup browser showing file sizes and times; download or delete. Scheduler with daily/weekly/monthly at set times. Optional Gotify push notifications. Logs panel with real-time output. Debian base, mobile-friendly dark UI.

📁 Paths: /config/remote_linux_backup/backups — backup storage. /config/remote_linux_backup/logs/app.log — runtime log. /config/remote_linux_backup/state — saved connections & schedules JSON.

⚙️ Configuration (flat JSON in options): {"timezone":"Africa/Johannesburg","ui_port":8066,"gotify_url":"","gotify_token":"","storage_path":"/config/remote_linux_backup/backups","auto_check_interval_hours":0}

🧪 Options: timezone — TZ for scheduler and timestamps. ui_port — web UI port (disable mapping if using Ingress). gotify_url, gotify_token — optional push. storage_path — where backups are written. auto_check_interval_hours — internal timer (0 to disable).

🌍 Web UI: Ingress or http://[HOST]:[PORT]. Tabs: Backup (Copy or Full Image), Restore (rsync folder or image->device), Connections (add/test servers), Backups (list, size, download, delete), Schedule (create recurring jobs), Notifications (Gotify test), Help (how to use and emergency restore command).

🧠 Self-hosting: All backups are ordinary files/folders. To restore without this UI: Copy type -> rsync the folder to the target machine. Image type -> gunzip -c your_image.img.gz | sudo dd of=/dev/sdX bs=4M status=progress. Ensure the destination device is correct and unmounted. No placeholders; all UI actions are wired to real logic.


## SMB/NFS mounts (non-SSH sources)

- Configure in **Mounts** tab: choose SMB or NFS, host, and share/export. Optional username/password for SMB, options field for advanced flags.
- Click **List** to discover SMB shares or NFS exports.
- Click **Mount**. The share/export is mounted to `/config/remote_linux_backup/mnt/<name>` and persists (auto-mount at startup if selected).
- In **Backup** tab, set **Source Type = SMB/NFS (mounted)**, select your mount name, and use the picker to choose a subfolder. Backups run locally (no SSH) using rsync.
- Restores to SMB/NFS: copy the backed up folder manually from Backups tab (Download) or mount the share and use any file manager. (UI restore target remains SSH or manual copy.)

### Directory structure

```
/config/remote_linux_backup/
  backups/                # where backups are stored (folders, and .img.gz images)
  logs/app.log            # runtime logs streamed to the UI footer
  mnt/<mount-name>/       # SMB/NFS mountpoints (mounted at runtime)
  state/
    connections.json      # saved SSH connections
    mounts.json           # saved SMB/NFS mounts (auto-mount config)
    schedules.json        # saved scheduler jobs
```


## Job queue, cancel, bandwidth limit
- Set **Max concurrent jobs** and default **bwlimit (KB/s)** under **Schedule → Jobs Config**.
- You can **Cancel Job** while a job is running.
- Per-run bandwidth caps: set **Max MB/s** on the Backup form. (Rsync uses `--bwlimit`, image uses `pv -L`.)

## Safer image restore
- Image backups now write `*.img.gz(.enc).sha256` and `*.meta.json` (host, device, bytes).
- Restore requires typing the **hostname** to confirm. Device size is checked; you can override with the **force** flag only via API (UI defaults to safe mode).

## Manifests and Verify
- Copy backups write a `manifest.json` (rel path, size, mtime) at the destination.
- Use **Verify** in Backups table to check integrity vs manifest.

## Mount health
- Background monitor probes mounts every 60s and auto-remounts when **Auto-retry** is enabled. Last error shows in the Mounts table.

## Export/Import & Logs
- **Backups → Export Settings** downloads a zip of `state/*.json`.
- **Backups → Download Logs** downloads a zip of log files.
- **Upload Backup** lets you upload archive or image files into `backups/uploads/` (zip files can be unpacked via API).

## Optional encryption for image backups
- Toggle **Encrypt image (AES-256)** and provide a passphrase. Output becomes `*.img.gz.enc`.
- Restore requires the same passphrase.

## System update (apt)
- **Notifications → System Update (apt)** runs `apt-get update && apt-get -y upgrade` inside the add-on. It will abort if Debian mirrors are unreachable.
