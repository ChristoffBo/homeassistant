#!/usr/bin/env python3
"""
Jarvis Prime - Backup Module
Agentless backup system with SSH/SMB/NFS support
Runs in separate process to avoid blocking main Jarvis
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
import sys

logger = logging.getLogger(__name__)

# Global manager for shared state
manager = Manager()
status_queue = Queue()

def backup_fanout_notify(
    job_id: str,
    job_name: str,
    status: str,
    source_path: str = None,
    dest_path: str = None,
    size_mb: float = None,
    duration: float = None,
    error: str = None,
    restore_id: str = None,
):
    """
    Fan-out detailed backup/restore job notification through Jarvis Prime's multi-channel system.
    """
    try:
        # Add parent directory to path to import bot
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from bot import process_incoming

        # Build message
        emoji = "✅" if status == "success" else "❌"
        title = f"{emoji} {'Restore' if restore_id else 'Backup'} {job_name}"

        message_parts = [
            f"**Status:** {status.upper()}",
            f"**{'Restore' if restore_id else 'Job'} ID:** {restore_id or job_id}",
        ]

        if source_path:
            message_parts.append(f"**Source:** {source_path}")
        if dest_path:
            message_parts.append(f"**Destination:** {dest_path}")
        if size_mb is not None:
            message_parts.append(f"**Size:** {size_mb:.2f} MB")
        if duration is not None:
            message_parts.append(f"**Duration:** {duration:.1f}s")
        if error:
            message_parts.append(f"**Error:** {error}")

        message = "\n".join(f"• {part}" for part in message_parts)

        priority = 3 if status == "success" else 8
        process_incoming(title, message, source="backup", priority=priority)
        logger.info(f"{'Restore' if restore_id else 'Backup'} notification sent for {restore_id or job_id}")

    except Exception as e:
        try:
            from errors import notify_error
            notify_error(f"[{'Restore' if restore_id else 'Backup'} Fanout Failure] {str(e)}", context="backup")
        except Exception:
            logger.error(f"{'Restore' if restore_id else 'Backup'} fanout failed: {e}")

class BackupConnection:
    """Base class for backup connections"""

    def __init__(self, connection_type: str, host: str, username: str, password: str, **kwargs):
        self.connection_type = connection_type
        self.host = host
        self.username = username
        self.password = password
        self.port = kwargs.get("port")
        self.share = kwargs.get("share")
        self.export_path = kwargs.get("export_path")
        self.connected = False

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def list_directory(self, path: str) -> List[Dict]:
        raise NotImplementedError

    def get_file(self, remote_path: str, local_path: str):
        raise NotImplementedError

    def put_file(self, local_path: str, remote_path: str):
        raise NotImplementedError

class SSHConnection(BackupConnection):
    """SSH/SFTP connection handler"""

    def __init__(self, host: str, username: str, password: str, port: int = 22):
        super().__init__("ssh", host, username, password, port=port)
        self.client = None
        self.sftp = None

    def connect(self):
        try:
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
            logger.info(f"SSH connected to {self.host}")
            return True
        except Exception as e:
            logger.error(f"SSH connection failed to {self.host}: {e}")
            return False

    def disconnect(self):
        try:
            if self.sftp:
                self.sftp.close()
            if self.client:
                self.client.close()
            self.connected = False
        except:
            pass

    def list_directory(self, path: str) -> List[Dict]:
        items = []
        try:
            attrs = self.sftp.listdir_attr(path)
            for attr in attrs:
                import stat
                item = {
                    "name": attr.filename,
                    "path": os.path.join(path, attr.filename),
                    "is_dir": stat.S_ISDIR(attr.st_mode),
                    "size": attr.st_size if hasattr(attr, "st_size") else 0,
                    "mtime": attr.st_mtime if hasattr(attr, "st_mtime") else 0,
                }
                items.append(item)
        except Exception as e:
            logger.error(f"Failed to list SSH directory {path}: {e}")
        return sorted(items, key=lambda x: (not x["is_dir"], x["name"]))

    def get_file(self, remote_path: str, local_path: str):
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            self.sftp.get(remote_path, local_path)
            logger.info(f"Downloaded {remote_path} to {local_path}")
        except Exception as e:
            logger.error(f"Failed to get file {remote_path}: {e}")
            raise

    def put_file(self, local_path: str, remote_path: str):
        try:
            self.sftp.put(local_path, remote_path)
            logger.info(f"Uploaded {local_path} to {remote_path}")
        except Exception as e:
            logger.error(f"Failed to put file {remote_path}: {e}")
            raise

    def execute_command(self, command: str) -> tuple:
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            output = stdout.read().decode("utf-8")
            error = stderr.read().decode("utf-8")
            return output, error
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return "", str(e)

class SMBConnection(BackupConnection):
    """SMB/CIFS connection handler"""

    def __init__(self, host: str, username: str, password: str, share: str, port: int = 445):
        super().__init__("smb", host, username, password, share=share, port=port)
        self.mount_point = None

    def connect(self):
        try:
            self.mount_point = tempfile.mkdtemp(prefix="jarvis_smb_")
            mount_cmd = [
                "mount",
                "-t",
                "cifs",
                f"//{self.host}/{self.share}",
                self.mount_point,
                "-o",
                f"username={self.username},password={self.password},vers=3.0",
            ]
            result = subprocess.run(mount_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.connected = True
                logger.info(f"SMB connected to //{self.host}/{self.share}")
                return True
            else:
                logger.error(f"SMB mount failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"SMB connection failed: {e}")
            return False

    def disconnect(self):
        try:
            if self.mount_point and os.path.exists(self.mount_point):
                subprocess.run(["umount", self.mount_point], capture_output=True)
                os.rmdir(self.mount_point)
            self.connected = False
        except:
            pass

    def list_directory(self, path: str) -> List[Dict]:
        items = []
        try:
            full_path = os.path.join(self.mount_point, path.lstrip("/"))
            for entry in os.listdir(full_path):
                entry_path = os.path.join(full_path, entry)
                stat_info = os.stat(entry_path)
                item = {
                    "name": entry,
                    "path": os.path.join(path, entry),
                    "is_dir": os.path.isdir(entry_path),
                    "size": stat_info.st_size,
                    "mtime": stat_info.st_mtime,
                }
                items.append(item)
        except Exception as e:
            logger.error(f"Failed to list SMB directory {path}: {e}")
        return sorted(items, key=lambda x: (not x["is_dir"], x["name"]))

    def get_file(self, remote_path: str, local_path: str):
        try:
            full_path = os.path.join(self.mount_point, remote_path.lstrip("/"))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            shutil.copy2(full_path, local_path)
            logger.info(f"Copied {full_path} to {local_path}")
        except Exception as e:
            logger.error(f"Failed to get file {remote_path}: {e}")
            raise

    def put_file(self, local_path: str, remote_path: str):
        try:
            full_path = os.path.join(self.mount_point, remote_path.lstrip("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            shutil.copy2(local_path, full_path)
            logger.info(f"Copied {local_path} to {full_path}")
        except Exception as e:
            logger.error(f"Failed to put file {remote_path}: {e}")
            raise

class NFSConnection(BackupConnection):
    """NFS connection handler"""

    def __init__(self, host: str, export_path: str, username: str = None, password: str = None):
        super().__init__("nfs", host, username or "", password or "", export_path=export_path)
        self.mount_point = None

    def connect(self):
        try:
            self.mount_point = tempfile.mkdtemp(prefix="jarvis_nfs_")
            mount_cmd = ["mount", "-t", "nfs", f"{self.host}:{self.export_path}", self.mount_point]
            result = subprocess.run(mount_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.connected = True
                logger.info(f"NFS connected to {self.host}:{self.export_path}")
                return True
            else:
                logger.error(f"NFS mount failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"NFS connection failed: {e}")
            return False

    def disconnect(self):
        try:
            if self.mount_point and os.path.exists(self.mount_point):
                subprocess.run(["umount", self.mount_point], capture_output=True)
                os.rmdir(self.mount_point)
            self.connected = False
        except:
            pass

    def list_directory(self, path: str) -> List[Dict]:
        items = []
        try:
            full_path = os.path.join(self.mount_point, path.lstrip("/"))
            for entry in os.listdir(full_path):
                entry_path = os.path.join(full_path, entry)
                stat_info = os.stat(entry_path)
                item = {
                    "name": entry,
                    "path": os.path.join(path, entry),
                    "is_dir": os.path.isdir(entry_path),
                    "size": stat_info.st_size,
                    "mtime": stat_info.st_mtime,
                }
                items.append(item)
        except Exception as e:
            logger.error(f"Failed to list NFS directory {path}: {e}")
        return sorted(items, key=lambda x: (not x["is_dir"], x["name"]))

    def get_file(self, remote_path: str, local_path: str):
        try:
            full_path = os.path.join(self.mount_point, remote_path.lstrip("/"))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            shutil.copy2(full_path, local_path)
            logger.info(f"Copied {full_path} to {local_path}")
        except Exception as e:
            logger.error(f"Failed to get file {remote_path}: {e}")
            raise

    def put_file(self, local_path: str, remote_path: str):
        try:
            full_path = os.path.join(self.mount_point, remote_path.lstrip("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            shutil.copy2(local_path, full_path)
            logger.info(f"Copied {local_path} to {full_path}")
        except Exception as e:
            logger.error(f"Failed to put file {remote_path}: {e}")
            raise

def create_connection(conn_type: str, **kwargs) -> BackupConnection:
    """Factory function to create connection objects"""
    if conn_type == "ssh":
        return SSHConnection(kwargs["host"], kwargs["username"], kwargs["password"], kwargs.get("port", 22))
    elif conn_type == "smb":
        return SMBConnection(
            kwargs["host"], kwargs["username"], kwargs["password"], kwargs["share"], kwargs.get("port", 445)
        )
    elif conn_type == "nfs":
        return NFSConnection(kwargs["host"], kwargs["export_path"], kwargs.get("username"), kwargs.get("password"))
    else:
        raise ValueError(f"Unknown connection type: {conn_type}")

def ensure_rsync_installed(ssh_conn):
    """Ensure rsync is installed on remote SSH server"""
    try:
        stdout, stderr = ssh_conn.execute_command("which rsync")
        if stdout.strip():
            return True
        logger.info(f"rsync not found on {ssh_conn.host}, attempting to install...")
        install_cmd = "sudo apt-get update && sudo apt-get install -y rsync || yum install -y rsync"
        stdout, stderr = ssh_conn.execute_command(install_cmd)
        stdout, stderr = ssh_conn.execute_command("which rsync")
        if stdout.strip():
            logger.info(f"Successfully installed rsync on {ssh_conn.host}")
            return True
        else:
            logger.warning(f"Failed to auto-install rsync on {ssh_conn.host}: {stderr}")
            return False
    except Exception as e:
        logger.error(f"Error checking/installing rsync: {e}")
        return False

def verify_tar_integrity(archive_path: str) -> bool:
    """Verify tar.gz file integrity"""
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.list()
        return True
    except tarfile.ReadError as e:
        logger.error(f"Tar integrity check failed for {archive_path}: {e}")
        return False

def create_archive_record(job_id: str, job_config: Dict, duration: float, data_dir: Path, archive_path: str):
    """Create archive record after successful backup"""
    archives_file = data_dir / "backup_archives.json"
    if archives_file.exists():
        with open(archives_file, "r") as f:
            archives = json.load(f)
    else:
        archives = []

    archive_id = str(uuid.uuid4())
    timestamp = datetime.now()
    size_mb = os.path.getsize(archive_path) / (1024 * 1024) if os.path.exists(archive_path) else 0

    archive = {
        "id": archive_id,
        "job_id": job_id,
        "job_name": job_config.get("name", "Unknown Job"),
        "source_paths": job_config.get("paths", []),
        "destination_path": str(Path(job_config.get("destination_path")) / f"{job_config.get('name')}/{Path(archive_path).name}"),
        "source_server_id": job_config.get("source_server_id"),
        "dest_server_id": job_config.get("destination_server_id"),
        "backup_type": job_config.get("backup_type", "full"),
        "compressed": job_config.get("compress", True),
        "size_mb": size_mb,
        "created_at": timestamp.isoformat(),
        "duration": duration,
        "status": "completed",
    }

    archives.append(archive)
    with open(archives_file, "w") as f:
        json.dump(archives, f, indent=2)

    logger.info(f"Created archive record {archive_id} for job {job_id}")

def apply_retention_policy(job_id: str, job_config: Dict, data_dir: Path):
    """Apply retention policy to delete old backups"""
    archives_file = data_dir / "backup_archives.json"
    if not archives_file.exists():
        return

    with open(archives_file, "r") as f:
        archives = json.load(f)

    job_archives = [a for a in archives if a["job_id"] == job_id]
    retention_days = job_config.get("retention_days", 30)
    retention_count = job_config.get("retention_count", 10)
    cutoff_date = datetime.now() - timedelta(days=retention_days)

    job_archives.sort(key=lambda x: x["created_at"], reverse=True)

    to_delete = []
    for idx, archive in enumerate(job_archives):
        created_at = datetime.fromisoformat(archive["created_at"])
        if idx >= retention_count or created_at < cutoff_date:
            to_delete.append(archive)

    for archive in to_delete:
        try:
            archives.remove(archive)
            servers_file = data_dir / "backup_servers.json"
            with open(servers_file, "r") as f:
                servers = json.load(f)
            dest_server = next((s for s in servers if s["id"] == archive["dest_server_id"]), None)
            if dest_server:
                conn = create_connection(dest_server["type"], **dest_server)
                if conn.connect():
                    if isinstance(conn, SSHConnection):
                        conn.sftp.remove(archive["destination_path"])
                    else:
                        full_path = os.path.join(conn.mount_point, archive["destination_path"].lstrip("/"))
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    conn.disconnect()
            logger.info(f"Deleted archive {archive['id']} due to retention policy")
        except Exception as e:
            logger.error(f"Failed to delete archive {archive['id']}: {e}")

    with open(archives_file, "w") as f:
        json.dump(archives, f, indent=2)

def import_existing_backups(data_dir: Path) -> List[Dict]:
    """Scan /data/backup_module for unlisted .tar.gz files and add to archives"""
    archives_file = data_dir / "backup_archives.json"
    if archives_file.exists():
        with open(archives_file, "r") as f:
            archives = json.load(f)
    else:
        archives = []

    existing_paths = {a["destination_path"] for a in archives}
    imported = []

    for job_dir in data_dir.glob("*/"):
        if not job_dir.is_dir() or job_dir.name in ["backup_jobs.json", "backup_servers.json", "backup_status.json"]:
            continue
        for file in job_dir.glob("*.tar.gz"):
            if str(file) not in existing_paths:
                archive_id = str(uuid.uuid4())
                size_mb = file.stat().st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(file.stat().st_mtime)
                archive = {
                    "id": archive_id,
                    "job_id": "imported",
                    "job_name": f"Imported {job_dir.name}",
                    "source_paths": [],
                    "destination_path": str(file),
                    "source_server_id": None,
                    "dest_server_id": None,
                    "backup_type": "full",
                    "compressed": True,
                    "size_mb": size_mb,
                    "created_at": mtime.isoformat(),
                    "duration": 0,
                    "status": "imported",
                }
                archives.append(archive)
                imported.append(archive)
                logger.info(f"Imported archive {archive_id} from {file}")

    with open(archives_file, "w") as f:
        json.dump(archives, f, indent=2)

    return imported

def backup_worker(job_id: str, job_config: Dict, status_queue: Queue):
    """
    Worker process for backup operations
    """
    start_time = time.time()
    job_config["start_time"] = start_time
    temp_dir = None

    try:
        logger.info(f"Backup worker started for job {job_id}")

        data_dir = Path(job_config.get("_data_dir", "/data/backup_module"))
        servers_file = data_dir / "backup_servers.json"
        if not servers_file.exists():
            raise Exception(f"No servers configured at {servers_file}")

        with open(servers_file, "r") as f:
            all_servers = json.load(f)

        source_server_id = job_config.get("source_server_id")
        if not source_server_id:
            raise Exception("No source server specified")
        source_server = next((s for s in all_servers if s.get("id") == source_server_id), None)
        if not source_server:
            raise Exception(f"Source server {source_server_id} not found")

        dest_server_id = job_config.get("destination_server_id")
        if not dest_server_id:
            raise Exception("No destination server specified")
        dest_server = next((s for s in all_servers if s.get("id") == dest_server_id), None)
        if not dest_server:
            raise Exception(f"Destination server {dest_server_id} not found")

        status_queue.put(
            {
                "job_id": job_id,
                "status": "running",
                "progress": 0,
                "message": f"Connecting to source: {source_server['name']} ({source_server['host']})...",
            }
        )

        source_conn = create_connection(source_server["type"], **source_server)
        if not source_conn.connect():
            raise Exception(f"Failed to connect to source server {source_server['name']}")

        if isinstance(source_conn, SSHConnection):
            ensure_rsync_installed(source_conn)

        status_queue.put(
            {
                "job_id": job_id,
                "status": "running",
                "progress": 10,
                "message": f"Connected to source. Connecting to destination: {dest_server['name']} ({dest_server['host']})...",
            }
        )

        dest_conn = create_connection(dest_server["type"], **dest_server)
        if not dest_conn.connect():
            source_conn.disconnect()
            raise Exception(f"Failed to connect to destination server {dest_server['name']}")

        if isinstance(dest_conn, SSHConnection):
            ensure_rsync_installed(dest_conn)

        status_queue.put({"job_id": job_id, "status": "running", "progress": 20, "message": "Connected to destination, starting backup..."})

        if job_config.get("stop_containers") and isinstance(source_conn, SSHConnection):
            for container in job_config.get("containers", []):
                source_conn.execute_command(f"docker stop {container}")
                time.sleep(2)

        backup_type = job_config.get("backup_type", "full")
        compress = job_config.get("compress", True)
        sync_mode = job_config.get("sync_mode", False)
        source_paths = job_config.get("paths") or job_config.get("source_paths", [])
        if not source_paths:
            raise Exception("No source paths specified")

        job_name = job_config.get("name", "unnamed_job")
        destination_path = Path(job_config.get("destination_path", "/backups")) / job_name
        temp_dir = tempfile.mkdtemp(prefix="jarvis_backup_")
        os.chmod(temp_dir, 0o755)  # Ensure temp directory is writable

        if sync_mode:
            success = perform_sync_backup(source_conn, dest_conn, source_paths, destination_path, status_queue, job_id)
        elif backup_type == "full":
            success = perform_full_backup(source_conn, dest_conn, source_paths, destination_path, compress, status_queue, job_id, temp_dir)
        else:
            success = perform_incremental_backup(source_conn, dest_conn, source_paths, destination_path, compress, status_queue, job_id)

        if job_config.get("stop_containers") and isinstance(source_conn, SSHConnection):
            for container in job_config.get("containers", []):
                source_conn.execute_command(f"docker start {container}")

        source_conn.disconnect()
        dest_conn.disconnect()

        if success:
            duration = time.time() - start_time
            archive_path = os.path.join(temp_dir, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz") if compress else temp_dir
            if not os.path.exists(archive_path):
                raise Exception(f"Archive not found at {archive_path} after backup")
            create_archive_record(job_id, job_config, duration, data_dir, archive_path)
            apply_retention_policy(job_id, job_config, data_dir)
            status_queue.put(
                {
                    "job_id": job_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "Backup completed successfully",
                    "completed_at": datetime.now().isoformat(),
                }
            )
            source_paths_str = ", ".join(source_paths[:3]) + (f" +{len(source_paths) - 3} more" if len(source_paths) > 3 else "")
            backup_fanout_notify(
                job_id=job_id,
                job_name=job_name,
                status="success",
                source_path=source_paths_str,
                dest_path=str(destination_path),
                duration=duration,
                size_mb=os.path.getsize(archive_path) / (1024 * 1024) if compress and os.path.exists(archive_path) else 0,
            )

    except Exception as e:
        import traceback
        error_msg = str(e)
        logger.error(f"Backup worker failed for job {job_id}: {error_msg}\n{traceback.format_exc()}")
        duration = time.time() - start_time
        status_queue.put(
            {
                "job_id": job_id,
                "status": "failed",
                "progress": 0,
                "message": f"Backup failed: {error_msg}",
                "failed_at": datetime.now().isoformat(),
            }
        )
        source_paths = job_config.get("paths") or job_config.get("source_paths", [])
        source_paths_str = ", ".join(source_paths[:3]) + (f" +{len(source_paths) - 3} more" if len(source_paths) > 3 else "")
        backup_fanout_notify(
            job_id=job_id,
            job_name=job_config.get("name", "Unknown Job"),
            status="failed",
            source_path=source_paths_str,
            dest_path=job_config.get("destination_path"),
            duration=duration,
            error=error_msg,
        )

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def perform_full_backup(source_conn, dest_conn, source_paths, dest_path, compress, status_queue, job_id, temp_dir):
    """Perform full backup with per-job folder structure"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_name = dest_path.name
        archive_name = f"backup_{timestamp}.tar.gz" if compress else f"backup_{timestamp}"
        archive_path = os.path.join(temp_dir, archive_name)

        for idx, source_path in enumerate(source_paths):
            progress = 30 + (idx * 40 // len(source_paths))
            status_queue.put(
                {
                    "job_id": job_id,
                    "status": "running",
                    "progress": progress,
                    "message": f"Backing up {source_path}...",
                }
            )
            if isinstance(source_conn, SSHConnection):
                download_via_rsync(source_conn, source_path, temp_dir)
            else:
                source_full = os.path.join(source_conn.mount_point, source_path.lstrip("/"))
                dest_full = os.path.join(temp_dir, os.path.basename(source_path))
                shutil.copytree(source_full, dest_full, dirs_exist_ok=True)

        if compress:
            status_queue.put({"job_id": job_id, "status": "running", "progress": 75, "message": "Compressing backup..."})
            with tarfile.open(archive_path, "w:gz") as tar:
                for item in os.listdir(temp_dir):
                    if item != archive_name:  # Avoid self-inclusion
                        tar.add(os.path.join(temp_dir, item), arcname=item)
            if not os.path.exists(archive_path):
                raise Exception(f"Failed to create archive at {archive_path}")
            shutil.rmtree(temp_dir, ignore_errors=True)  # Clean up source files
            os.makedirs(temp_dir, exist_ok=True)  # Recreate for move
            shutil.move(archive_path, os.path.join(temp_dir, archive_name))  # Ensure move succeeds
            upload_file = archive_path
            is_archive = True
        else:
            upload_file = temp_dir
            is_archive = False

        status_queue.put({"job_id": job_id, "status": "running", "progress": 85, "message": "Uploading to destination..."})
        dest_full_path = str(dest_path)
        if isinstance(dest_conn, SSHConnection):
            if is_archive:
                dest_conn.put_file(upload_file, os.path.join(dest_full_path, archive_name))
            else:
                upload_via_rsync(dest_conn, upload_file, dest_full_path)
        else:
            dest_full_path = os.path.join(dest_conn.mount_point, dest_full_path.lstrip("/"))
            os.makedirs(dest_full_path, exist_ok=True)
            if is_archive:
                shutil.copy2(upload_file, os.path.join(dest_full_path, archive_name))
            else:
                for item in os.listdir(upload_file):
                    src = os.path.join(upload_file, item)
                    dst = os.path.join(dest_full_path, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)

        return True

    except Exception as e:
        status_queue.put({"job_id": job_id, "status": "failed", "progress": 0, "message": f"Backup failed: {str(e)}"})
        raise

def perform_incremental_backup(source_conn, dest_conn, source_paths, dest_path, compress, status_queue, job_id):
    """Perform incremental backup (only changed files)"""
    try:
        for idx, source_path in enumerate(source_paths):
            progress = 30 + (idx * 60 // len(source_paths))
            status_queue.put(
                {
                    "job_id": job_id,
                    "status": "running",
                    "progress": progress,
                    "message": f"Syncing {source_path}...",
                }
            )
            if isinstance(source_conn, SSHConnection) and isinstance(dest_conn, SSHConnection):
                temp_dir = tempfile.mkdtemp(prefix="jarvis_sync_")
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
            elif isinstance(source_conn, SSHConnection):
                temp_dir = tempfile.mkdtemp(prefix="jarvis_sync_")
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                dest_full_path = os.path.join(dest_conn.mount_point, str(dest_path).lstrip("/"), os.path.basename(source_path))
                sync_directories(temp_dir, dest_full_path)
                shutil.rmtree(temp_dir)
            elif isinstance(dest_conn, SSHConnection):
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip("/"))
                temp_dir = tempfile.mkdtemp(prefix="jarvis_sync_")
                sync_directories(source_full_path, temp_dir)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
            else:
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip("/"))
                dest_full_path = os.path.join(dest_conn.mount_point, str(dest_path).lstrip("/"), os.path.basename(source_path))
                sync_directories(source_full_path, dest_full_path)
        return True
    except Exception as e:
        status_queue.put({"job_id": job_id, "status": "failed", "progress": 0, "message": f"Backup failed: {str(e)}"})
        raise

def perform_sync_backup(source_conn, dest_conn, source_paths, dest_path, status_queue, job_id):
    """Perform rsync-based sync backup"""
    try:
        for idx, source_path in enumerate(source_paths):
            progress = 30 + (idx * 60 // len(source_paths))
            status_queue.put(
                {
                    "job_id": job_id,
                    "status": "running",
                    "progress": progress,
                    "message": f"Syncing {source_path}...",
                }
            )
            if isinstance(source_conn, SSHConnection) and isinstance(dest_conn, SSHConnection):
                rsync_cmd = [
                    "rsync",
                    "-avz",
                    "--update",
                    "-e",
                    f"sshpass -p '{source_conn.password}' ssh -o StrictHostKeyChecking=no -p {source_conn.port}",
                    f"{source_conn.username}@{source_conn.host}:{source_path}/",
                    f"{dest_conn.username}@{dest_conn.host}:{dest_path}/{os.path.basename(source_path)}/",
                ]
                subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
            elif isinstance(source_conn, SSHConnection):
                temp_dir = tempfile.mkdtemp(prefix="jarvis_sync_")
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                dest_full_path = os.path.join(dest_conn.mount_point, str(dest_path).lstrip("/"), os.path.basename(source_path))
                sync_directories(temp_dir, dest_full_path)
                shutil.rmtree(temp_dir)
            elif isinstance(dest_conn, SSHConnection):
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip("/"))
                temp_dir = tempfile.mkdtemp(prefix="jarvis_sync_")
                sync_directories(source_full_path, temp_dir)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
            else:
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip("/"))
                dest_full_path = os.path.join(dest_conn.mount_point, str(dest_path).lstrip("/"), os.path.basename(source_path))
                sync_directories(source_full_path, dest_full_path)
        return True
    except Exception as e:
        status_queue.put({"job_id": job_id, "status": "failed", "progress": 0, "message": f"Sync failed: {str(e)}"})
        raise

def download_via_rsync(ssh_conn, remote_path, local_path, incremental=False):
    """Download using rsync over SSH (with SFTP fallback)"""
    os.makedirs(local_path, exist_ok=True)
    try:
        subprocess.run(["which", "rsync"], check=True, capture_output=True)
        subprocess.run(["which", "sshpass"], check=True, capture_output=True)
        has_rsync = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_rsync = False

    if not has_rsync:
        logger.warning("rsync not available, using SFTP fallback")
        download_via_sftp(ssh_conn, remote_path, local_path)
        return

    rsync_cmd = [
        "rsync",
        "-avz",
        "--progress",
        "-e",
        f"sshpass -p '{ssh_conn.password}' ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}",
        f"{ssh_conn.username}@{ssh_conn.host}:{remote_path}/",
        local_path + "/",
    ]
    if incremental:
        rsync_cmd.insert(2, "--update")
    try:
        subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"rsync failed (exit code {e.returncode}): {e.stderr or e.stdout}")

def download_via_sftp(ssh_conn, remote_path, local_path):
    """Download using SFTP"""
    import stat
    try:
        remote_stat = ssh_conn.sftp.stat(remote_path)
        if stat.S_ISDIR(remote_stat.st_mode):
            os.makedirs(local_path, exist_ok=True)
            for item in ssh_conn.sftp.listdir_attr(remote_path):
                remote_item = os.path.join(remote_path, item.filename)
                local_item = os.path.join(local_path, item.filename)
                if stat.S_ISDIR(item.st_mode):
                    download_via_sftp(ssh_conn, remote_item, local_item)
                else:
                    ssh_conn.get_file(remote_item, local_item)
        else:
            ssh_conn.get_file(remote_path, os.path.join(local_path, os.path.basename(remote_path)))
    except Exception as e:
        raise Exception(f"SFTP download failed: {str(e)}")

def upload_via_rsync(ssh_conn, local_path, remote_path):
    """Upload using rsync over SSH (with SFTP fallback)"""
    try:
        subprocess.run(["which", "rsync"], check=True, capture_output=True)
        subprocess.run(["which", "sshpass"], check=True, capture_output=True)
        has_rsync = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_rsync = False

    if not has_rsync:
        logger.warning("rsync not available, using SFTP fallback")
        upload_via_sftp(ssh_conn, local_path, remote_path)
        return

    rsync_cmd = [
        "rsync",
        "-avz",
        "--progress",
        "-e",
        f"sshpass -p '{ssh_conn.password}' ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}",
        local_path + ("/" if os.path.isdir(local_path) else ""),
        f"{ssh_conn.username}@{ssh_conn.host}:{remote_path}/",
    ]
    try:
        subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"rsync failed (exit code {e.returncode}): {e.stderr or e.stdout}")

def upload_via_sftp(ssh_conn, local_path, remote_path):
    """Upload using SFTP"""
    import stat
    try:
        try:
            ssh_conn.sftp.stat(remote_path)
        except:
            ssh_conn.sftp.mkdir(remote_path)
        if os.path.isdir(local_path):
            for item in os.listdir(local_path):
                local_item = os.path.join(local_path, item)
                remote_item = os.path.join(remote_path, item)
                if os.path.isdir(local_item):
                    upload_via_sftp(ssh_conn, local_item, remote_item)
                else:
                    ssh_conn.put_file(local_item, remote_item)
        else:
            ssh_conn.put_file(local_path, os.path.join(remote_path, os.path.basename(local_path)))
    except Exception as e:
        raise Exception(f"SFTP upload failed: {str(e)}")

def sync_directories(source, dest):
    """Sync directories (incremental copy)"""
    os.makedirs(dest, exist_ok=True)
    for root, dirs, files in os.walk(source):
        rel_path = os.path.relpath(root, source)
        dest_root = os.path.join(dest, rel_path) if rel_path != "." else dest
        os.makedirs(dest_root, exist_ok=True)
        for file in files:
            source_file = os.path.join(root, file)
            dest_file = os.path.join(dest_root, file)
            if not os.path.exists(dest_file) or os.path.getmtime(source_file) > os.path.getmtime(dest_file):
                shutil.copy2(source_file, dest_file)

def restore_worker(restore_id: str, restore_config: Dict, status_queue: Queue):
    """
    Worker function for restore operations
    """
    start_time = time.time()
    temp_dir = None

    try:
        logger.info(f"Restore worker started for {restore_id}")

        archive = restore_config["archive"]
        dest_server_id = restore_config["dest_server_id"]
        dest_path = restore_config["dest_path"]
        use_original = restore_config.get("use_original", False)
        data_dir = Path(restore_config["_data_dir"])

        status_queue.put({"restore_id": restore_id, "status": "running", "progress": 10, "message": "Loading server configurations..."})

        servers_file = data_dir / "backup_servers.json"
        with open(servers_file, "r") as f:
            all_servers = json.load(f)

        source_server_id = archive.get("dest_server_id")
        source_server = next((s for s in all_servers if s["id"] == source_server_id), None)
        if not source_server:
            raise Exception(f"Backup storage server not found: {source_server_id}")

        dest_server = next((s for s in all_servers if s["id"] == dest_server_id), None)
        if not dest_server:
            raise Exception(f"Restore destination server not found: {dest_server_id}")

        status_queue.put(
            {
                "restore_id": restore_id,
                "status": "running",
                "progress": 20,
                "message": f"Connecting to backup storage: {source_server['name']}...",
            }
        )

        source_conn = create_connection(source_server["type"], **source_server)
        if not source_conn.connect():
            raise Exception(f"Failed to connect to backup storage: {source_server['name']}")

        status_queue.put(
            {
                "restore_id": restore_id,
                "status": "running",
                "progress": 40,
                "message": f"Connecting to restore destination: {dest_server['name']}...",
            }
        )

        dest_conn = create_connection(dest_server["type"], **dest_server)
        if not dest_conn.connect():
            source_conn.disconnect()
            raise Exception(f"Failed to connect to restore destination: {dest_server['name']}")

        status_queue.put({"restore_id": restore_id, "status": "running", "progress": 60, "message": "Verifying archive integrity..."})

        temp_dir = tempfile.mkdtemp(prefix="jarvis_restore_")
        archive_path = archive.get("destination_path")
        local_archive = os.path.join(temp_dir, os.path.basename(archive_path))

        if isinstance(source_conn, SSHConnection):
            source_conn.get_file(archive_path, local_archive)
        else:
            source_full = os.path.join(source_conn.mount_point, archive_path.lstrip("/"))
            shutil.copy2(source_full, local_archive)

        if archive.get("compressed", True):
            if not verify_tar_integrity(local_archive):
                raise Exception("Archive integrity check failed")

            status_queue.put({"restore_id": restore_id, "status": "running", "progress": 70, "message": "Extracting archive..."})
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(local_archive, "r:gz") as tar:
                tar.extractall(path=extract_dir)
            os.remove(local_archive)
            upload_dir = extract_dir
        else:
            upload_dir = local_archive

        status_queue.put({"restore_id": restore_id, "status": "running", "progress": 80, "message": f"Uploading to {dest_path}..."})

        final_dest_path = dest_path
        if use_original:
            final_dest_path = archive.get("source_paths", [""])[0] or dest_path

        if isinstance(dest_conn, SSHConnection):
            upload_via_sftp(dest_conn, upload_dir, final_dest_path)
        else:
            dest_full = os.path.join(dest_conn.mount_point, final_dest_path.lstrip("/"))
            os.makedirs(dest_full, exist_ok=True)
            for item in os.listdir(upload_dir):
                src = os.path.join(upload_dir, item)
                dst = os.path.join(dest_full, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)

        source_conn.disconnect()
        dest_conn.disconnect()
        duration = time.time() - start_time

        status_queue.put(
            {
                "restore_id": restore_id,
                "status": "completed",
                "progress": 100,
                "message": f"Restore completed in {duration:.1f}s",
                "completed_at": datetime.now().isoformat(),
            }
        )

        backup_fanout_notify(
            job_id=archive["job_id"],
            job_name=archive["job_name"],
            status="success",
            source_path=archive_path,
            dest_path=final_dest_path,
            duration=duration,
            size_mb=archive.get("size_mb", 0),
            restore_id=restore_id,
        )

    except Exception as e:
        import traceback
        logger.error(f"Restore worker failed: {str(e)}\n{traceback.format_exc()}")
        status_queue.put(
            {
                "restore_id": restore_id,
                "status": "failed",
                "progress": 0,
                "message": f"Restore failed: {str(e)}",
                "failed_at": datetime.now().isoformat(),
            }
        )
        backup_fanout_notify(
            job_id=archive["job_id"],
            job_name=archive["job_name"],
            status="failed",
            source_path=archive_path,
            dest_path=dest_path,
            duration=time.time() - start_time,
            error=str(e),
            restore_id=restore_id,
        )

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

class BackupManager:
    """Main backup manager - runs in Jarvis main process"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.data_dir / "backup_jobs.json"
        self.status_file = self.data_dir / "backup_status.json"
        self.jobs = self._load_jobs()
        self.statuses = self._load_statuses()
        self.worker_processes = {}
        self.status_updater = None
        self.scheduler_task = None

    def _load_jobs(self):
        if self.jobs_file.exists():
            with open(self.jobs_file, "r") as f:
                return json.load(f)
        return {}

    def _save_jobs(self):
        with open(self.jobs_file, "w") as f:
            json.dump(self.jobs, f, indent=2)

    def _load_statuses(self):
        if self.status_file.exists():
            with open(self.status_file, "r") as f:
                return json.load(f)
        return {}

    def _save_statuses(self):
        with open(self.status_file, "w") as f:
            json.dump(self.statuses, f, indent=2)

    async def start(self):
        self.status_updater = asyncio.create_task(self._status_updater())
        self.scheduler_task = asyncio.create_task(self._schedule_jobs())
        logger.info("Backup manager started")

    async def stop(self):
        if self.status_updater:
            self.status_updater.cancel()
        if self.scheduler_task:
            self.scheduler_task.cancel()
        for process in self.worker_processes.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        logger.info("Backup manager stopped")

    async def _status_updater(self):
        while True:
            try:
                while not status_queue.empty():
                    status_update = status_queue.get_nowait()
                    id_key = "restore_id" if "restore_id" in status_update else "job_id"
                    job_id = status_update[id_key]
                    if job_id not in self.statuses:
                        self.statuses[job_id] = {}
                    self.statuses[job_id].update(status_update)
                    self._save_statuses()
                    logger.info(f"{'Restore' if id_key == 'restore_id' else 'Job'} {job_id}: {status_update.get('message', 'Status update')}")
                finished = []
                for job_id, process in self.worker_processes.items():
                    if not process.is_alive():
                        finished.append(job_id)
                for job_id in finished:
                    del self.worker_processes[job_id]
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Status updater error: {e}")
                await asyncio.sleep(1)

    async def _schedule_jobs(self):
        while True:
            try:
                for job_id, job_config in self.jobs.items():
                    if job_config.get("sync_mode", False):
                        schedule_hours = job_config.get("schedule_hours", 24)
                        last_run = self.statuses.get(job_id, {}).get("completed_at")
                        if last_run:
                            last_run_time = datetime.fromisoformat(last_run)
                            if (datetime.now() - last_run_time).total_seconds() / 3600 >= schedule_hours:
                                self.run_job(job_id)
                        else:
                            self.run_job(job_id)
                await asyncio.sleep(3600)  # Check every hour
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)

    def create_job(self, job_config: Dict) -> str:
        job_id = str(uuid.uuid4())
        job_config["id"] = job_id
        job_config["created_at"] = datetime.now().isoformat()
        self.jobs[job_id] = job_config
        self._save_jobs()
        logger.info(f"Created backup job {job_id}")
        return job_id

    def run_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            logger.error(f"Job {job_id} not found")
            return False
        if job_id in self.worker_processes and self.worker_processes[job_id].is_alive():
            logger.warning(f"Job {job_id} is already running")
            return False
        job_config = self.jobs[job_id].copy()
        job_config["_data_dir"] = str(self.data_dir)
        process = Process(target=backup_worker, args=(job_id, job_config, status_queue))
        process.start()
        self.worker_processes[job_id] = process
        self.statuses[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Job queued",
            "started_at": datetime.now().isoformat(),
        }
        self._save_statuses()
        logger.info(f"Started backup job {job_id} in process {process.pid}")
        return True

    def get_job_status(self, job_id: str) -> Dict:
        return self.statuses.get(job_id, {})

    def get_all_jobs(self) -> Dict:
        return self.jobs

    def delete_job(self, job_id: str) -> bool:
        if job_id in self.jobs:
            del self.jobs[job_id]
            self._save_jobs()
            if job_id in self.statuses:
                del self.statuses[job_id]
                self._save_statuses()
            logger.info(f"Deleted backup job {job_id}")
            return True
        return False

    def get_all_servers(self) -> List[Dict]:
        servers_file = self.data_dir / "backup_servers.json"
        if servers_file.exists():
            with open(servers_file, "r") as f:
                return json.load(f)
        return []

    def add_server(self, server_config: Dict) -> str:
        server_id = str(uuid.uuid4())
        server_config["id"] = server_id
        servers = self.get_all_servers()
        servers.append(server_config)
        servers_file = self.data_dir / "backup_servers.json"
        with open(servers_file, "w") as f:
            json.dump(servers, f, indent=2)
        logger.info(f"Added server {server_id}")
        return server_id

    def delete_server(self, server_id: str) -> bool:
        servers = self.get_all_servers()
        filtered = [s for s in servers if s.get("id") != server_id]
        if len(filtered) < len(servers):
            servers_file = self.data_dir / "backup_servers.json"
            with open(servers_file, "w") as f:
                json.dump(filtered, f, indent=2)
            logger.info(f"Deleted server {server_id}")
            return True
        return False

    def get_all_archives(self) -> List[Dict]:
        archives_file = self.data_dir / "backup_archives.json"
        if archives_file.exists():
            with open(archives_file, "r") as f:
                return json.load(f)
        return []

    def delete_archive(self, archive_id: str) -> bool:
        archives = self.get_all_archives()
        filtered = [a for a in archives if a.get("id") != archive_id]
        if len(filtered) < len(archives):
            archives_file = self.data_dir / "backup_archives.json"
            with open(archives_file, "w") as f:
                json.dump(filtered, f, indent=2)
            logger.info(f"Deleted archive {archive_id}")
            return True
        return False

    def start_restore(self, archive_id: str, dest_server_id: str, dest_path: str, use_original: bool, overwrite: bool) -> str:
        archives = self.get_all_archives()
        archive = next((a for a in archives if a["id"] == archive_id), None)
        if not archive:
            raise Exception(f"Archive {archive_id} not found")
        restore_id = str(uuid.uuid4())
        restore_config = {
            "restore_id": restore_id,
            "archive": archive,
            "dest_server_id": dest_server_id,
            "dest_path": dest_path,
            "use_original": use_original,
            "overwrite": overwrite,
            "_data_dir": str(self.data_dir),
        }
        process = Process(target=restore_worker, args=(restore_id, restore_config, status_queue))
        process.start()
        self.worker_processes[restore_id] = process
        self.statuses[restore_id] = {
            "restore_id": restore_id,
            "status": "queued",
            "progress": 0,
            "message": "Restore queued",
            "started_at": datetime.now().isoformat(),
        }
        self._save_statuses()
        logger.info(f"Started restore {restore_id} for archive {archive_id}")
        return restore_id

    def import_archives(self) -> List[Dict]:
        return import_existing_backups(self.data_dir)

async def init_backup_module(app):
    global backup_manager
    data_dir = app.get("data_dir", "/data") + "/backup_module"
    backup_manager = BackupManager(data_dir)
    await backup_manager.start()
    logger.info("Backup module initialized")

async def cleanup_backup_module(app):
    global backup_manager
    if backup_manager:
        await backup_manager.stop()

async def test_connection(request):
    try:
        data = await request.json()
        conn = create_connection(data["type"], **data)
        if conn.connect():
            conn.disconnect()
            return web.json_response({"success": True, "message": "Connection successful"})
        else:
            return web.json_response({"success": False, "message": "Connection failed"}, status=400)
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return web.json_response({"success": False, "message": str(e)}, status=500)

async def browse_directory(request):
    try:
        data = await request.json()
        server_config = data.get("server_config") or data.get("connection")
        if not server_config:
            return web.json_response({"success": False, "message": "No server configuration provided"}, status=400)
        conn = create_connection(server_config["type"], **server_config)
        if not conn.connect():
            return web.json_response({"success": False, "message": "Failed to connect to server"}, status=400)
        path = data.get("path", "/")
        items = conn.list_directory(path)
        conn.disconnect()
        return web.json_response({"success": True, "files": items})
    except Exception as e:
        logger.error(f"Directory browse failed: {e}")
        return web.json_response({"success": False, "message": str(e)}, status=500)

async def create_backup_job(request):
    try:
        data = await request.json()
        job_id = backup_manager.create_job(data)
        return web.json_response({"success": True, "job_id": job_id})
    except Exception as e:
        logger.error(f"Job creation failed: {e}")
        return web.json_response({"success": False, "message": str(e)}, status=500)

async def run_backup_job(request):
    try:
        job_id = request.match_info["job_id"]
        success = backup_manager.run_job(job_id)
        if success:
            return web.json_response({"success": True, "message": "Job started"})
        else:
            return web.json_response({"success": False, "message": "Failed to start job"}, status=400)
    except Exception as e:
        logger.error(f"Job run failed: {e}")
        return web.json_response({"success": False, "message": str(e)}, status=500)

async def get_job_status(request):
    try:
        job_id = request.match_info["job_id"]
        status = backup_manager.get_job_status(job_id)
        return web.json_response({"success": True, "status": status})
    except Exception as e:
        logger.error(f"Get status failed: {e}")
        return web.json_response({"success": False, "message": str(e)}, status=500)

async def get_all_jobs(request):
    try:
        jobs_dict = backup_manager.get_all_jobs()
        jobs_list = list(jobs_dict.values())
        return web.json_response({"jobs": jobs_list})
    except Exception as e:
        logger.error(f"Get jobs failed: {e}")
        return web.json_response({"success": False, "message": str(e)}, status=500)

async def delete_backup_job(request):
    try:
        job_id = request.match_info["job_id"]
        success = backup_manager.delete_job(job_id)
        if success:
            return web.json_response({"success": True, "message": "Job deleted"})
        else:
            return web.json_response({"success": False, "message": "Job not found"}, status=404)
    except Exception as e:
        logger.error(f"Job deletion failed: {e}")
        return web.json_response({"success": False, "message": str(e)}, status=500)

async def get_servers(request):
    try:
        servers = backup_manager.get_all_servers()
        source_servers = [s for s in servers if s.get("server_type") == "source"]
        destination_servers = [s for s in servers if s.get("server_type") == "destination"]
        return web.json_response({"source_servers": source_servers, "destination_servers": destination_servers})
    except Exception as e:
        logger.error(f"Failed to get servers: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def add_server(request):
    try:
        data = await request.json()
        server_id = backup_manager.add_server(data)
        return web.json_response({"success": True, "id": server_id, "message": "Server added successfully"})
    except Exception as e:
        logger.error(f"Failed to add server: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def delete_server(request):
    try:
        server_id = request.match_info["server_id"]
        success = backup_manager.delete_server(server_id)
        if success:
            return web.json_response({"success": True, "message": "Server deleted"})
        else:
            return web.json_response({"error": "Server not found"}, status=404)
    except Exception as e:
        logger.error(f"Failed to delete server: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_archives(request):
    try:
        archives = backup_manager.get_all_archives()
        return web.json_response({"archives": archives})
    except Exception as e:
        logger.error(f"Failed to get archives: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def delete_archive(request):
    try:
        archive_id = request.match_info["archive_id"]
        success = backup_manager.delete_archive(archive_id)
        if success:
            return web.json_response({"success": True, "message": "Archive deleted"})
        else:
            return web.json_response({"error": "Archive not found"}, status=404)
    except Exception as e:
        logger.error(f"Failed to delete archive: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def restore_backup(request):
    try:
        data = await request.json()
        archive_id = data.get("archive_id")
        dest_server_id = data.get("destination_server_id")
        dest_path = data.get("destination_path")
        use_original = data.get("use_original", False)
        overwrite = data.get("overwrite", False)
        if not all([archive_id, dest_server_id, dest_path]):
            return web.json_response(
                {"error": "Missing required fields: archive_id, destination_server_id, destination_path"}, status=400
            )
        restore_id = backup_manager.start_restore(archive_id, dest_server_id, dest_path, use_original, overwrite)
        return web.json_response({"success": True, "restore_id": restore_id, "message": "Restore started"})
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def import_archives(request):
    try:
        imported = backup_manager.import_archives()
        return web.json_response({"success": True, "imported": imported})
    except Exception as e:
        logger.error(f"Import archives failed: {e}")
        return web.json_response({"error": str(e)}, status=500)

def setup_routes(app):
    app.router.add_post("/api/backup/jobs", create_backup_job)
    app.router.add_get("/api/backup/jobs", get_all_jobs)
    app.router.add_post("/api/backup/jobs/{job_id}/run", run_backup_job)
    app.router.add_get("/api/backup/jobs/{job_id}/status", get_job_status)
    app.router.add_delete("/api/backup/jobs/{job_id}", delete_backup_job)
    app.router.add_get("/api/backup/servers", get_servers)
    app.router.add_post("/api/backup/servers", add_server)
    app.router.add_delete("/api/backup/servers/{server_id}", delete_server)
    app.router.add_get("/api/backup/archives", get_archives)
    app.router.add_delete("/api/backup/archives/{archive_id}", delete_archive)
    app.router.add_post("/api/backup/test-connection", test_connection)
    app.router.add_post("/api/backup/browse", browse_directory)
    app.router.add_post("/api/backup/restore", restore_backup)
    app.router.add_post("/api/backup/import-archives", import_archives)
    app.on_startup.append(init_backup_module)
    app.on_cleanup.append(cleanup_backup_module)