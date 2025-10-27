#!/usr/bin/env python3
"""
Jarvis Prime - Backup Module (Phase 2)
Complete agentless backup system with restore, sync, retention, and import support.
Supports SSH, SMB, NFS connections. Fully asynchronous with per-job folders.
"""

import os
import json
import asyncio
import logging
import tarfile
import tempfile
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from aiohttp import web
import paramiko
from multiprocessing import Process, Queue, Manager
import subprocess
import time

logger = logging.getLogger("backup_module")

# Global manager for shared state
manager = Manager()
status_queue = Queue()


# ============================================================================
# CONNECTION CLASSES
# ============================================================================

class BackupConnection:
    """Base connection class"""
    def __init__(self, connection_type: str, host: str, username: str, password: str, **kwargs):
        self.connection_type = connection_type
        self.host = host
        self.username = username
        self.password = password
        self.port = kwargs.get("port", 22)
        self.share = kwargs.get("share")
        self.export_path = kwargs.get("export_path")
        self.connected = False

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        pass


class SSHConnection(BackupConnection):
    """Handles SSH/SFTP backup transfers"""

    def connect(self):
        logger.info(f"[SSH] Connecting to {self.host}:{self.port}")
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=10,
        )
        self.sftp = self.client.open_sftp()
        self.connected = True

    def upload(self, local_path: str, remote_path: str):
        if not self.connected:
            self.connect()
        logger.info(f"[SSH] Uploading {local_path} → {remote_path}")
        self.sftp.put(local_path, remote_path)

    def download(self, remote_path: str, local_path: str):
        if not self.connected:
            self.connect()
        logger.info(f"[SSH] Downloading {remote_path} → {local_path}")
        self.sftp.get(remote_path, local_path)

    def mkdir(self, path: str):
        try:
            self.sftp.mkdir(path)
        except IOError:
            pass

    def disconnect(self):
        if self.connected:
            self.sftp.close()
            self.client.close()
            self.connected = False


# ============================================================================
# BACKUP MANAGER CORE
# ============================================================================

class BackupManager:
    """Main backup manager - runs inside Jarvis Prime process"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.data_dir / "backup_jobs.json"
        self.status_file = self.data_dir / "backup_status.json"
        self.archives_file = self.data_dir / "backup_archives.json"
        self.servers_file = self.data_dir / "backup_servers.json"

        self.jobs = self._load_json(self.jobs_file)
        self.statuses = self._load_json(self.status_file)
        self.worker_processes: Dict[str, Process] = {}

    # ------------------------------------------------------------------------
    # JSON Helpers
    # ------------------------------------------------------------------------

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {path}: {e}")
            return {}

    def _save_json(self, path: Path, data: dict):
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write {path}: {e}")

    # ------------------------------------------------------------------------
    # Server Management
    # ------------------------------------------------------------------------

    def get_all_servers(self) -> List[Dict]:
        if not self.servers_file.exists():
            return []
        try:
            with open(self.servers_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load servers: {e}")
            return []

    def add_server(self, server_config: Dict) -> str:
        server_id = str(uuid.uuid4())
        server_config["id"] = server_id

        # Ensure server_type persists
        if not server_config.get("server_type"):
            conn_type = server_config.get("type", "")
            server_config["server_type"] = "source" if conn_type == "ssh" else "destination"

        servers = self.get_all_servers()
        servers.append(server_config)
        self._save_json(self.servers_file, servers)
        logger.info(f"Added server {server_id} ({server_config['server_type']})")
        return server_id
# ------------------------------------------------------------------------
    # Job Handling
    # ------------------------------------------------------------------------

    def save_job(self, job_config: Dict) -> str:
        """Add or update a backup job"""
        job_id = job_config.get("id") or str(uuid.uuid4())
        job_config["id"] = job_id
        self.jobs[job_id] = job_config
        self._save_json(self.jobs_file, self.jobs)
        logger.info(f"Saved job {job_id}: {job_config.get('name')}")
        return job_id

    def delete_job(self, job_id: str):
        if job_id in self.jobs:
            del self.jobs[job_id]
            self._save_json(self.jobs_file, self.jobs)
            logger.info(f"Deleted job {job_id}")

    # ------------------------------------------------------------------------
    # Job Backup Folder & Retention
    # ------------------------------------------------------------------------

    def get_job_backup_folder(self, job_name: str) -> Path:
        """Get or create folder for a specific job"""
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in job_name)
        folder = self.data_dir / safe_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def apply_retention_policy(self, job_id: str):
        """Clean up old backups based on job settings"""
        try:
            job_config = self.jobs.get(job_id)
            if not job_config:
                logger.warning(f"Retention skipped — job {job_id} not found")
                return

            retention_days = job_config.get("retention_days", 30)
            retention_count = job_config.get("retention_count", 10)
            if retention_days == 0 and retention_count == 0:
                return

            logger.info(f"Applying retention policy: {retention_count} files, {retention_days} days")

            if not self.archives_file.exists():
                return

            with open(self.archives_file, "r") as f:
                archives = json.load(f)

            job_archives = [a for a in archives if a.get("job_id") == job_id]
            job_archives.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            cutoff = datetime.now() - timedelta(days=retention_days) if retention_days > 0 else None
            archives_to_delete = []

            if retention_count > 0 and len(job_archives) > retention_count:
                archives_to_delete.extend(job_archives[retention_count:])

            if cutoff:
                for archive in job_archives:
                    try:
                        created = datetime.fromisoformat(archive.get("created_at"))
                        if created < cutoff and archive not in archives_to_delete:
                            archives_to_delete.append(archive)
                    except Exception:
                        continue

            for arc in archives_to_delete:
                try:
                    path = Path(arc["path"])
                    if path.exists():
                        path.unlink()
                        logger.info(f"Deleted expired backup: {path}")
                except Exception as e:
                    logger.warning(f"Failed deleting {arc.get('path')}: {e}")

            # prune record list
            new_archives = [a for a in archives if a not in archives_to_delete]
            with open(self.archives_file, "w") as f:
                json.dump(new_archives, f, indent=2)

        except Exception as e:
            logger.error(f"Retention error for {job_id}: {e}")

    # ------------------------------------------------------------------------
    # Core Backup Workflow
    # ------------------------------------------------------------------------

    def run_backup(self, job_id: str):
        """Launch a background backup worker"""
        if job_id not in self.jobs:
            logger.error(f"Job {job_id} not found")
            return False

        job = self.jobs[job_id]
        proc = Process(target=self._backup_worker, args=(job,))
        proc.start()
        self.worker_processes[job_id] = proc
        logger.info(f"Started backup worker for {job_id}")
        return True

    def _backup_worker(self, job: Dict):
        """Executed in a separate process"""
        job_id = job["id"]
        name = job.get("name", "unnamed_job")
        source_path = job.get("source_path")
        target_dir = job.get("target_dir", str(self.data_dir))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        folder = self.get_job_backup_folder(name)
        archive_name = f"{name}_{timestamp}.tar.gz"
        archive_path = folder / archive_name

        self._update_status(job_id, "running", f"Creating archive {archive_name}")
        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(source_path, arcname=os.path.basename(source_path))
            logger.info(f"Created archive: {archive_path}")

            self._record_archive(job_id, str(archive_path))
            self.apply_retention_policy(job_id)
            self._update_status(job_id, "completed", f"Backup complete: {archive_name}")
        except Exception as e:
            self._update_status(job_id, "failed", str(e))
            logger.error(f"Backup failed: {e}")

    # ------------------------------------------------------------------------
    # Status + Archive Tracking
    # ------------------------------------------------------------------------

    def _update_status(self, job_id: str, state: str, message: str):
        self.statuses[job_id] = {"state": state, "message": message, "timestamp": datetime.now().isoformat()}
        self._save_json(self.status_file, self.statuses)

    def _record_archive(self, job_id: str, path: str):
        record = {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "path": path,
            "created_at": datetime.now().isoformat(),
        }
        archives = []
        if self.archives_file.exists():
            with open(self.archives_file, "r") as f:
                archives = json.load(f)
        archives.append(record)
        with open(self.archives_file, "w") as f:
            json.dump(archives, f, indent=2)
# ------------------------------------------------------------------------
    # Restore Logic (real extraction)
    # ------------------------------------------------------------------------

    def restore_backup(self, archive_id: str, target_path: Optional[str] = None):
        """Restore an existing backup archive to a destination folder."""
        if not self.archives_file.exists():
            raise FileNotFoundError("No archives file found")

        with open(self.archives_file, "r") as f:
            archives = json.load(f)

        archive_entry = next((a for a in archives if a["id"] == archive_id), None)
        if not archive_entry:
            raise ValueError(f"Archive {archive_id} not found")

        archive_path = Path(archive_entry["path"])
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive missing: {archive_path}")

        # Determine restore target
        dest = Path(target_path) if target_path else archive_path.parent / "restore_output"
        dest.mkdir(parents=True, exist_ok=True)

        job_id = archive_entry.get("job_id", "unknown")
        self._update_status(job_id, "restoring", f"Extracting {archive_path} → {dest}")

        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(dest)
            logger.info(f"Restored archive {archive_path} to {dest}")
            self._update_status(job_id, "restored", f"Restored to {dest}")
            return str(dest)
        except Exception as e:
            logger.error(f"Restore failed for {archive_path}: {e}")
            self._update_status(job_id, "failed", str(e))
            raise

    # ------------------------------------------------------------------------
    # Import Existing Archives (for reloaded systems)
    # ------------------------------------------------------------------------

    def import_existing_backups(self):
        """Scan all job folders and import any unindexed .tar.gz archives."""
        imported = 0
        archives = []
        if self.archives_file.exists():
            with open(self.archives_file, "r") as f:
                archives = json.load(f)

        indexed_paths = {a["path"] for a in archives}

        for folder in self.data_dir.iterdir():
            if folder.is_dir():
                for file in folder.glob("*.tar.gz"):
                    if str(file) not in indexed_paths:
                        record = {
                            "id": str(uuid.uuid4()),
                            "job_id": "imported",
                            "path": str(file),
                            "created_at": datetime.fromtimestamp(file.stat().st_mtime).isoformat(),
                        }
                        archives.append(record)
                        imported += 1

        with open(self.archives_file, "w") as f:
            json.dump(archives, f, indent=2)

        logger.info(f"Imported {imported} existing archives")
        return imported

    # ------------------------------------------------------------------------
    # Async Sync Mode
    # ------------------------------------------------------------------------

    async def sync_job(self, job_id: str):
        """Synchronize source → destination for this job (rsync-style)"""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        src = job.get("source_path")
        dst = job.get("target_dir")
        if not src or not dst:
            raise ValueError("Missing source or destination in job")

        logger.info(f"Starting async sync for job {job_id}: {src} → {dst}")
        self._update_status(job_id, "syncing", f"Syncing {src} → {dst}")

        try:
            proc = await asyncio.create_subprocess_exec(
                "rsync", "-avz", "--delete", src + "/", dst + "/",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                msg = f"Sync completed for {job_id}"
                logger.info(msg)
                self._update_status(job_id, "synced", msg)
            else:
                msg = f"Sync failed for {job_id}: {stderr.decode()}"
                logger.error(msg)
                self._update_status(job_id, "failed", msg)

        except FileNotFoundError:
            err = "rsync not found in container"
            logger.error(err)
            self._update_status(job_id, "failed", err)
        except Exception as e:
            self._update_status(job_id, "failed", str(e))
            logger.error(f"Sync error: {e}")
# ============================================================================
# AIOHTTP WEB ROUTES
# ============================================================================

backup_manager: Optional[BackupManager] = None


async def list_jobs(request):
    """Return all configured backup jobs."""
    try:
        return web.json_response({"jobs": list(backup_manager.jobs.values())})
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def add_job(request):
    """Add or update a backup job."""
    try:
        data = await request.json()
        job_id = backup_manager.save_job(data)
        return web.json_response({"success": True, "id": job_id})
    except Exception as e:
        logger.error(f"Failed to save job: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def delete_job(request):
    """Delete a job by ID."""
    try:
        job_id = request.match_info["job_id"]
        backup_manager.delete_job(job_id)
        return web.json_response({"success": True})
    except Exception as e:
        logger.error(f"Failed to delete job: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def start_backup(request):
    """Run a backup immediately."""
    try:
        job_id = request.match_info["job_id"]
        backup_manager.run_backup(job_id)
        return web.json_response({"success": True, "message": "Backup started"})
    except Exception as e:
        logger.error(f"Failed to start backup: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def restore_archive(request):
    """Restore a backup archive."""
    try:
        data = await request.json()
        archive_id = data.get("archive_id")
        target = data.get("target_path")
        restored_path = backup_manager.restore_backup(archive_id, target)
        return web.json_response({"success": True, "restored_to": restored_path})
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def sync_job(request):
    """Async rsync between job source and destination."""
    try:
        job_id = request.match_info["job_id"]
        asyncio.create_task(backup_manager.sync_job(job_id))
        return web.json_response({"success": True, "message": "Sync started"})
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def import_backups(request):
    """Import untracked backups."""
    try:
        count = backup_manager.import_existing_backups()
        return web.json_response({"success": True, "imported": count})
    except Exception as e:
        logger.error(f"Import failed: {e}")
        return web.json_response({"error": str(e)}, status=500)


# ------------------------------------------------------------------------
# Server Management API
# ------------------------------------------------------------------------

async def get_servers(request):
    """Return all configured backup servers."""
    try:
        servers = backup_manager.get_all_servers()
        src = [s for s in servers if s.get("server_type") == "source"]
        dst = [s for s in servers if s.get("server_type") == "destination"]
        return web.json_response({
            "source_servers": src,
            "destination_servers": dst
        })
    except Exception as e:
        logger.error(f"Failed to get servers: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def add_server(request):
    """Add a server configuration."""
    try:
        data = await request.json()
        if not data.get("server_type"):
            conn_type = data.get("type", "")
            data["server_type"] = "source" if conn_type == "ssh" else "destination"
        server_id = backup_manager.add_server(data)
        return web.json_response({"success": True, "id": server_id})
    except Exception as e:
        logger.error(f"Failed to add server: {e}")
        return web.json_response({"error": str(e)}, status=500)
# ------------------------------------------------------------------------
# WEB APP INITIALIZATION & ROUTE SETUP
# ------------------------------------------------------------------------

def setup_routes(app: web.Application, manager: "BackupManager"):
    """Register all backup API routes into the aiohttp app."""
    global backup_manager
    backup_manager = manager

    # Job management
    app.router.add_get("/api/backup/jobs", list_jobs)
    app.router.add_post("/api/backup/jobs", add_job)
    app.router.add_delete("/api/backup/jobs/{job_id}", delete_job)
    app.router.add_post("/api/backup/jobs/{job_id}/run", start_backup)
    app.router.add_post("/api/backup/jobs/{job_id}/sync", sync_job)

    # Restore
    app.router.add_post("/api/backup/restore", restore_archive)

    # Server management
    app.router.add_get("/api/backup/servers", get_servers)
    app.router.add_post("/api/backup/servers", add_server)

    # Archive import
    app.router.add_post("/api/backup/import", import_backups)

    logger.info("✅ Backup routes initialized.")


# ------------------------------------------------------------------------
# AUTO-RETENTION & PERIODIC CLEANUP TASKS
# ------------------------------------------------------------------------

async def retention_loop(app: web.Application):
    """Background task that runs retention every 12 hours."""
    while True:
        try:
            if backup_manager and backup_manager.jobs:
                logger.info("🧹 Running scheduled retention cleanup...")
                for jid in list(backup_manager.jobs.keys()):
                    backup_manager.apply_retention_policy(jid)
            else:
                logger.debug("No jobs available for retention sweep.")
        except Exception as e:
            logger.error(f"Retention loop error: {e}")

        await asyncio.sleep(12 * 3600)  # every 12 hours


async def on_startup(app: web.Application):
    """Initialize BackupManager and spawn background tasks."""
    logger.info("🚀 Initializing Backup Manager...")
    data_dir = Path("/data/backups")
    data_dir.mkdir(parents=True, exist_ok=True)
    manager = BackupManager(data_dir)
    setup_routes(app, manager)

    # Spawn retention coroutine
    app["retention_task"] = asyncio.create_task(retention_loop(app))
    logger.info("Backup Manager ready and retention task scheduled.")


async def on_cleanup(app: web.Application):
    """Ensure background tasks exit cleanly on shutdown."""
    logger.info("🧽 Cleaning up backup services...")
    task = app.get("retention_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Backup Manager shutdown complete.")
# ------------------------------------------------------------------------
# BACKUP MANAGER CLASS (core definition)
# ------------------------------------------------------------------------

class BackupManager:
    """Primary orchestrator for backup, restore, retention, and server configs."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.jobs_file = self.data_dir / "jobs.json"
        self.servers_file = self.data_dir / "servers.json"
        self.status_file = self.data_dir / "status.json"
        self.archives_file = self.data_dir / "archives.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.jobs = self._load_json(self.jobs_file, {})
        self.status = self._load_json(self.status_file, {})
        logger.info(f"BackupManager initialized in {self.data_dir}")

    # ---------------------- Generic JSON I/O ----------------------

    def _load_json(self, file: Path, default):
        if not file.exists():
            return default
        try:
            with open(file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {file}: {e}")
            return default

    def _save_json(self, file: Path, data):
        try:
            with open(file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {file}: {e}")

    # ---------------------- Job & Status --------------------------

    def save_job(self, job: dict) -> str:
        job_id = job.get("id") or str(uuid.uuid4())
        job["id"] = job_id
        self.jobs[job_id] = job
        self._save_json(self.jobs_file, self.jobs)
        logger.info(f"Saved job {job_id}")
        return job_id

    def delete_job(self, job_id: str):
        if job_id in self.jobs:
            del self.jobs[job_id]
            self._save_json(self.jobs_file, self.jobs)
            logger.info(f"Deleted job {job_id}")

    def _update_status(self, job_id: str, state: str, message: str):
        self.status[job_id] = {
            "state": state,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        self._save_json(self.status_file, self.status)

    # ---------------------- Retention Policy ----------------------

    def apply_retention_policy(self, job_id: str):
        """Delete old archives based on retention_days in job config."""
        job = self.jobs.get(job_id)
        if not job:
            return

        days = job.get("retention_days", 7)
        cutoff = datetime.now().timestamp() - (days * 86400)

        archives = self._load_json(self.archives_file, [])
        kept, deleted = [], 0
        for a in archives:
            try:
                ts = datetime.fromisoformat(a["created_at"]).timestamp()
                if ts < cutoff:
                    file = Path(a["path"])
                    if file.exists():
                        file.unlink()
                    deleted += 1
                else:
                    kept.append(a)
            except Exception:
                kept.append(a)

        self._save_json(self.archives_file, kept)
        if deleted:
            logger.info(f"Retention cleaned {deleted} old archives for job {job_id}")

    # ---------------------- Server Configs ------------------------

    def get_all_servers(self):
        return self._load_json(self.servers_file, [])

    def add_server(self, cfg: dict) -> str:
        cfg["id"] = str(uuid.uuid4())
        servers = self.get_all_servers()
        servers.append(cfg)
        self._save_json(self.servers_file, servers)
        return cfg["id"]

    # ---------------------- Run Backup ----------------------------

    def run_backup(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        src = job.get("source_path")
        dst = job.get("target_dir")
        if not src or not dst:
            raise ValueError("Missing source or target path in job")

        logger.info(f"Starting backup job {job_id}: {src} → {dst}")
        self._update_status(job_id, "running", "Backup started")

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_dir = Path(dst) / f"{Path(src).name}_{timestamp}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            archive_path = shutil.make_archive(str(dest_dir), "gztar", src)
            size_mb = os.path.getsize(archive_path) / (1024 * 1024)
            self._update_status(job_id, "completed",
                                f"Backup done ({size_mb:.1f} MB)")
        except Exception as e:
            logger.error(f"Backup job {job_id} failed: {e}")
            self._update_status(job_id, "failed", str(e))
            raise