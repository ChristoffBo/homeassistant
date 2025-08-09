# Remote Linux Backup (Home Assistant add-on)

Back up and restore remote Linux systems over SSH. Methods: dd (disk image), rsync (files), ZFS snapshots.
Destinations: local /backup, mounted NAS (CIFS/NFS), Dropbox (rclone). Scheduler + Gotify notifications.

## Key features
- SSH Port support
- pigz compression (faster) with gzip fallback
- SHA256 checksum + optional verification for dd images
- Bandwidth limit (KB/s) for dd/rsync/rclone
- Rsync exclude patterns
- Retention pruning (delete files older than N days)
- UI: descriptive fields, no raw JSON needed
- Persistence at `/data/options.json`

## NAS mounts in add-on options
`proto=cifs;server=10.0.0.2;share=backups;mount=/mnt/nas/backups;username=user;password=pass;options=vers=3.0`
or
`proto=nfs;server=10.0.0.3;share=/export/backups;mount=/mnt/nas/backs`

## Jobs
Use the Jobs tab to create schedules; click *Apply schedule* to write cron under `/etc/cron.d/remote_linux_backup`.
