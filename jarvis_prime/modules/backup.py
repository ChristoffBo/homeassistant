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

logger = logging.getLogger(__name__)

# Global manager for shared state
manager = Manager()
status_queue = Queue()

def backup_fanout_notify(job_id: str, job_name: str, status: str, source_path: str = None,
                         dest_path: str = None, size_mb: float = None, duration: float = None,
                         error: str = None, restore: bool = False):
    """
    Fan-out detailed backup/restore job notification through Jarvis Prime's multi-channel system.
    """
    try:
        import sys
        import textwrap
       
        # Add parent directory to path to import bot
        sys.path.insert(0, str(Path(__file__).resolve().parent))
       
        from bot import process_incoming
       
        # Build message
        kind = "Restore" if restore else "Backup"
        emoji = "✅" if status == "success" else "❌"
        title = f"{emoji} {kind} {job_name}"
       
        message_parts = [
            f"**Status:** {status.upper()}",
            f"**Job ID:** {job_id}"
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
        logger.info(f"{kind} notification sent for job {job_id}")
       
    except Exception as e:
        # Fallback to error notification if available
        try:
            from errors import notify_error
            notify_error(f"[{kind} Fanout Failure] {str(e)}", context="backup")
        except Exception:
            logger.error(f"{kind} fanout failed: {e}")

class BackupConnection:
    """Base class for backup connections"""
   
    def __init__(self, connection_type: str, host: str, username: str, password: str, **kwargs):
        self.connection_type = connection_type
        self.host = host
        self.username = username
        self.password = password
        self.port = kwargs.get('port')
        self.share = kwargs.get('share')
        self.export_path = kwargs.get('export_path')
        self.connected = False
       
    def connect(self):
        """Connect to remote system"""
        raise NotImplementedError
       
    def disconnect(self):
        """Disconnect from remote system"""
        raise NotImplementedError
       
    def list_directory(self, path: str) -> List[Dict]:
        """List directory contents"""
        raise NotImplementedError

class SSHConnection(BackupConnection):
    """SSH/SFTP connection handler"""
   
    def __init__(self, host: str, username: str, password: str, port: int = 22):
        super().__init__('ssh', host, username, password, port=port)
        self.client = None
        self.sftp = None
       
    def connect(self):
        """Connect via SSH"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=10
            )
            self.sftp = self.client.open_sftp()
            self.connected = True
            logger.info(f"SSH connected to {self.host}")
            return True
           
        except Exception as e:
            logger.error(f"SSH connection failed to {self.host}: {e}")
            return False
           
    def disconnect(self):
        """Disconnect SSH"""
        try:
            if self.sftp:
                self.sftp.close()
            if self.client:
                self.client.close()
            self.connected = False
        except:
            pass
       
    def list_directory(self, path: str) -> List[Dict]:
        """List directory contents via SFTP"""
        items = []
        try:
            attrs = self.sftp.listdir_attr(path)
        except:
            return []
       
        for attr in attrs:
            import stat
            item = {
                'name': attr.filename,
                'path': os.path.join(path, attr.filename),
                'is_dir': stat.S_ISDIR(attr.st_mode),
                'size': attr.st_size if hasattr(attr, 'st_size') else 0,
                'mtime': attr.st_mtime if hasattr(attr, 'st_mtime') else 0
            }
            items.append(item)
           
        return sorted(items, key=lambda x: (not x['is_dir'], x['name']))
           
    def execute_command(self, command: str) -> tuple:
        """Execute command on remote system"""
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            return output, error
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return "", str(e)

class SMBConnection(BackupConnection):
    """SMB/CIFS connection handler"""
   
    def __init__(self, host: str, username: str, password: str, share: str, port: int = 445):
        super().__init__('smb', host, username, password, port=port, share=share)
        self.mount_point = None
       
    def connect(self):
        """Connect via SMB by mounting share"""
        try:
            self.mount_point = tempfile.mkdtemp(prefix='jarvis_smb_')
           
            mount_cmd = [
                'mount',
                '-t', 'cifs',
                f'//{self.host}/{self.share}',
                self.mount_point,
                '-o', f'username={self.username},password={self.password},vers=3.0'
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
        """Disconnect SMB"""
        try:
            if self.mount_point and os.path.exists(self.mount_point):
                subprocess.run(['umount', self.mount_point], capture_output=True)
                os.rmdir(self.mount_point)
            self.connected = False
        except:
            pass
       
    def list_directory(self, path: str) -> List[Dict]:
        """List directory contents from mounted SMB share"""
        full_path = os.path.join(self.mount_point, path.lstrip('/'))
        items = []
       
        try:
            for entry in os.listdir(full_path):
                entry_path = os.path.join(full_path, entry)
                stat_info = os.stat(entry_path)
               
                item = {
                    'name': entry,
                    'path': os.path.join(path, entry),
                    'is_dir': os.path.isdir(entry_path),
                    'size': stat_info.st_size,
                    'mtime': stat_info.st_mtime
                }
                items.append(item)
        except:
            pass
           
        return sorted(items, key=lambda x: (not x['is_dir'], x['name']))

class NFSConnection(BackupConnection):
    """NFS connection handler"""
   
    def __init__(self, host: str, export_path: str, username: str = None, password: str = None):
        super().__init__('nfs', host, username or '', password or '', export_path=export_path)
        self.mount_point = None
       
    def connect(self):
        """Connect via NFS by mounting export"""
        try:
            self.mount_point = tempfile.mkdtemp(prefix='jarvis_nfs_')
           
            mount_cmd = [
                'mount',
                '-t', 'nfs',
                f'{self.host}:{self.export_path}',
                self.mount_point
            ]
           
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
        """Disconnect NFS"""
        try:
            if self.mount_point and os.path.exists(self.mount_point):
                subprocess.run(['umount', self.mount_point], capture_output=True)
                os.rmdir(self.mount_point)
            self.connected = False
        except:
            pass
       
    def list_directory(self, path: str) -> List[Dict]:
        """List directory contents from mounted NFS export"""
        try:
            full_path = os.path.join(self.mount_point, path.lstrip('/'))
            items = []
           
            for entry in os.listdir(full_path):
                entry_path = os.path.join(full_path, entry)
                stat_info = os.stat(entry_path)
               
                item = {
                    'name': entry,
                    'path': os.path.join(path, entry),
                    'is_dir': os.path.isdir(entry_path),
                    'size': stat_info.st_size,
                    'mtime': stat_info.st_mtime
                }
                items.append(item)
               
            return sorted(items, key=lambda x: (not x['is_dir'], x['name']))
           
        except Exception as e:
            logger.error(f"Failed to list NFS directory {path}: {e}")
            return []

def create_connection(conn_type: str, **kwargs) -> BackupConnection:
    """Factory function to create connection objects"""
    if conn_type == 'ssh':
        return SSHConnection(
            kwargs['host'],
            kwargs['username'],
            kwargs['password'],
            kwargs.get('port', 22)
        )
    elif conn_type == 'smb':
        return SMBConnection(
            kwargs['host'],
            kwargs['username'],
            kwargs['password'],
            kwargs['share'],
            kwargs.get('port', 445)
        )
    elif conn_type == 'nfs':
        return NFSConnection(
            kwargs['host'],
            kwargs['export_path'],
            kwargs.get('username'),
            kwargs.get('password')
        )
    else:
        raise ValueError(f"Unknown connection type: {conn_type}")

def ensure_rsync_installed(ssh_conn):
    """Ensure rsync is installed on remote SSH server"""
    try:
        stdout, stderr = ssh_conn.execute_command('which rsync')
        if stdout.strip():
            return True
       
        logger.info(f"rsync not found on {ssh_conn.host}, attempting to install...")
        install_cmd = 'sudo apt-get update && sudo apt-get install -y rsync || yum install -y rsync'
        ssh_conn.execute_command(install_cmd)
        stdout, _ = ssh_conn.execute_command('which rsync')
        if stdout.strip():
            logger.info(f"Successfully installed rsync on {ssh_conn.host}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking/installing rsync: {e}")
        return False

def get_job_archive_dir(data_dir: Path, job_name: str) -> Path:
    """Get per-job archive directory"""
    job_dir = data_dir / job_name.replace(' ', '_')
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir

def delete_remote_directory(conn, remote_path: str):
    """Delete a directory on remote server"""
    try:
        if isinstance(conn, SSHConnection):
            # Use SSH command to delete
            conn.execute_command(f"rm -rf '{remote_path}'")
            logger.info(f"Deleted remote directory via SSH: {remote_path}")
        elif isinstance(conn, (SMBConnection, NFSConnection)):
            # Delete via mounted filesystem
            full_path = os.path.join(conn.mount_point, remote_path.lstrip('/'))
            if os.path.exists(full_path):
                shutil.rmtree(full_path)
                logger.info(f"Deleted remote directory via mount: {full_path}")
    except Exception as e:
        logger.error(f"Failed to delete remote directory {remote_path}: {e}")
        raise

def apply_retention(data_dir: Path, job_name: str, retention_days: int, retention_count: int,
                   dest_server_config: Dict, dest_path: str):
    """Apply retention policy: delete old timestamped backup folders from both local and remote"""
    try:
        # Normalize job name to match folder structure
        job_name_normalized = job_name.replace(' ', '_')
        job_dir = get_job_archive_dir(data_dir, job_name)
        
        # Find all timestamped subfolders
        timestamp_folders = []
        for folder in job_dir.iterdir():
            if folder.is_dir():
                try:
                    # Timestamp folders are named YYYYMMDD_HHMMSS
                    stat_info = folder.stat()
                    timestamp_folders.append({
                        'path': folder,
                        'name': folder.name,
                        'mtime': stat_info.st_mtime
                    })
                except:
                    continue
       
        if not timestamp_folders:
            logger.info(f"No backup folders found for retention cleanup in {job_name}")
            return
       
        # Sort by modification time (newest first)
        timestamp_folders.sort(key=lambda x: x['mtime'], reverse=True)
       
        cutoff = datetime.now() - timedelta(days=retention_days)
       
        to_delete = []
       
        # Delete by age (if retention_days > 0)
        if retention_days > 0:
            for folder in timestamp_folders:
                if datetime.fromtimestamp(folder['mtime']) < cutoff:
                    to_delete.append(folder)
       
        # Delete by count (keep latest N) - if retention_count > 0
        if retention_count > 0 and len(timestamp_folders) > retention_count:
            for folder in timestamp_folders[retention_count:]:
                if folder not in to_delete:
                    to_delete.append(folder)
       
        if not to_delete:
            logger.info(f"No backups to delete for {job_name} (retention: {retention_days}d, keep: {retention_count})")
            return
       
        logger.info(f"Retention cleanup for {job_name}: deleting {len(to_delete)} old backups")
       
        # Connect to destination server to delete remote folders
        dest_conn = None
        try:
            dest_conn = create_connection(dest_server_config['type'], **dest_server_config)
            if dest_conn.connect():
                for folder_info in to_delete:
                    timestamp_name = folder_info['name']
                    
                    # Delete remote folder FIRST
                    try:
                        remote_folder = f"{dest_path.rstrip('/')}/{job_name_normalized}/{timestamp_name}"
                        logger.info(f"Deleting remote folder: {remote_folder}")
                        
                        if isinstance(dest_conn, SSHConnection):
                            stdout, stderr = dest_conn.execute_command(f"rm -rf '{remote_folder}'")
                            if stderr and "No such file" not in stderr:
                                logger.error(f"Remote delete stderr: {stderr}")
                            else:
                                logger.info(f"Deleted remote backup folder: {remote_folder}")
                        elif isinstance(dest_conn, (SMBConnection, NFSConnection)):
                            full_path = os.path.join(dest_conn.mount_point, remote_folder.lstrip('/'))
                            if os.path.exists(full_path):
                                shutil.rmtree(full_path)
                                logger.info(f"Deleted remote backup folder: {full_path}")
                    except Exception as e:
                        logger.error(f"Failed to delete remote folder {remote_folder}: {e}")
                    
                    # Delete local folder
                    try:
                        shutil.rmtree(folder_info['path'])
                        logger.info(f"Deleted local backup folder: {folder_info['path']}")
                    except Exception as e:
                        logger.error(f"Failed to delete local folder {folder_info['path']}: {e}")
                
                dest_conn.disconnect()
               
        except Exception as e:
            logger.error(f"Failed to connect to destination for retention cleanup: {e}")
        finally:
            if dest_conn and dest_conn.connected:
                dest_conn.disconnect()
               
    except Exception as e:
        logger.error(f"Retention cleanup failed for {job_name}: {e}", exc_info=True)

def create_archive_record(archive_id: str, job_id: str, job_config: Dict, duration: float,
                         archive_path: Path, size_mb: float, data_dir: Path):
    """Create archive record after successful backup"""
    archives_file = data_dir / 'backup_archives.json'
   
    if archives_file.exists():
        with open(archives_file, 'r') as f:
            archives = json.load(f)
    else:
        archives = []
   
    timestamp = datetime.now()
   
    archive = {
        'id': archive_id,
        'job_id': job_id,
        'job_name': job_config.get('name', 'Unknown Job'),
        'source_paths': job_config.get('paths', []),
        'destination_path': job_config.get('destination_path'),
        'source_server_id': job_config.get('source_server_id'),
        'dest_server_id': job_config.get('destination_server_id'),
        'backup_type': job_config.get('backup_type', 'full'),
        'compressed': job_config.get('compress', True),
        'size_mb': size_mb,
        'archive_path': str(archive_path),
        'created_at': timestamp.isoformat(),
        'duration': duration,
        'status': 'completed'
    }
   
    archives.append(archive)
   
    with open(archives_file, 'w') as f:
        json.dump(archives, f, indent=2)
   
    logger.info(f"Created archive record {archive_id}")

def import_existing_archives(data_dir: Path):
    """Scan for .tar.gz not in backup_archives.json and import them"""
    archives_file = data_dir / 'backup_archives.json'
    existing_paths = set()
   
    if archives_file.exists():
        with open(archives_file, 'r') as f:
            existing = json.load(f)
            existing_paths = {a.get('archive_path') for a in existing if a.get('archive_path')}
   
    imported = 0
    for job_dir in data_dir.iterdir():
        if not job_dir.is_dir() or job_dir.name.startswith('.'):
            continue
        for archive_path in job_dir.glob("**/*.tar.gz"):
            if str(archive_path) not in existing_paths:
                # Try to infer job name
                job_name = job_dir.name.replace('_', ' ')
                archive_id = str(uuid.uuid4())
               
                record = {
                    'id': archive_id,
                    'job_id': None,
                    'job_name': f"Imported: {job_name}",
                    'source_paths': [],
                    'destination_path': None,
                    'source_server_id': None,
                    'dest_server_id': None,
                    'backup_type': 'imported',
                    'compressed': True,
                    'size_mb': archive_path.stat().st_size / (1024*1024),
                    'archive_path': str(archive_path),
                    'created_at': datetime.fromtimestamp(archive_path.stat().st_mtime).isoformat(),
                    'duration': 0,
                    'status': 'imported'
                }
               
                if archives_file.exists():
                    with open(archives_file, 'r') as f:
                        existing = json.load(f)
                    existing.append(record)
                    with open(archives_file, 'w') as f:
                        json.dump(existing, f, indent=2)
                else:
                    with open(archives_file, 'w') as f:
                        json.dump([record], f, indent=2)
                imported += 1
   
    return imported

def verify_tar_integrity(archive_path: Path) -> bool:
    """Verify tar.gz integrity"""
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.getmembers()
        return True
    except Exception as e:
        logger.error(f"Tar integrity check failed for {archive_path}: {e}")
        return False

def safe_add(tar, path, arcname=""):
    """Safely add file or directory to tar, skipping on permission errors"""
    try:
        tar.add(path, arcname=arcname, recursive=True)
    except PermissionError:
        logger.warning(f"Skipped (no permission): {path}")
    except Exception as e:
        logger.warning(f"Skipped {path}: {e}")

def backup_worker(job_id: str, job_config: Dict, status_queue: Queue):
    """
    Worker function that runs in separate process
    Performs the actual backup operation
    """
    start_time = time.time()
    job_config['start_time'] = start_time
   
    try:
        logger.info(f"Backup worker started for job {job_id}")
       
        data_dir = Path(job_config.get('_data_dir', '/data/backup_module'))
        servers_file = data_dir / 'backup_servers.json'
       
        if not servers_file.exists():
            raise Exception(f"No servers configured. Looking in: {servers_file}")
       
        with open(servers_file, 'r') as f:
            all_servers = json.load(f)
       
        source_server_id = job_config.get('source_server_id')
        if not source_server_id:
            raise Exception("No source server specified")
       
        source_server = next((s for s in all_servers if s.get('id') == source_server_id), None)
        if not source_server:
            raise Exception(f"Source server '{source_server_id}' not found")
       
        dest_server_id = job_config.get('destination_server_id')
        if not dest_server_id:
            raise Exception("No destination server specified")
           
        dest_server = next((s for s in all_servers if s.get('id') == dest_server_id), None)
        if not dest_server:
            raise Exception(f"Destination server '{dest_server_id}' not found")
       
        job_name = job_config.get('name', 'Unknown Job')
        job_archive_dir = get_job_archive_dir(data_dir, job_name)
       
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 0,
            'message': f'Connecting to source: {source_server["name"]}...'
        })
       
        source_conn = create_connection(source_server['type'], **source_server)
        if not source_conn.connect():
            raise Exception(f"Failed to connect to source {source_server['name']}")
       
        if isinstance(source_conn, SSHConnection):
            ensure_rsync_installed(source_conn)
           
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 10,
            'message': f'Connecting to destination: {dest_server["name"]}...'
        })
       
        dest_conn = create_connection(dest_server['type'], **dest_server)
        if not dest_conn.connect():
            source_conn.disconnect()
            raise Exception(f"Failed to connect to destination {dest_server['name']}")
       
        if isinstance(dest_conn, SSHConnection):
            ensure_rsync_installed(dest_conn)
           
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 20,
            'message': 'Starting backup...'
        })
       
        if job_config.get('stop_containers') and isinstance(source_conn, SSHConnection):
            for container in job_config.get('containers', []):
                source_conn.execute_command(f"docker stop {container}")
                time.sleep(2)
       
        source_paths = job_config.get('paths') or job_config.get('source_paths', [])
        if not source_paths:
            raise Exception("No source paths specified")
       
        destination_path = job_config.get('destination_path', '/backups')
        compress = job_config.get('compress', True)
        sync_mode = job_config.get('sync_mode', False)
       
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
       
        if sync_mode:
            success = perform_sync_mode(
                source_conn, dest_conn, source_paths, destination_path,
                status_queue, job_id, job_archive_dir, timestamp
            )
        elif job_config.get('backup_type', 'incremental') == 'full':
            success = perform_full_backup(
                source_conn, dest_conn, source_paths, destination_path,
                compress, status_queue, job_id, job_archive_dir, timestamp,
                job_config, data_dir
            )
        else:
            success = perform_incremental_backup(
                source_conn, dest_conn, source_paths, destination_path,
                status_queue, job_id, job_archive_dir
            )
       
        if job_config.get('stop_containers') and isinstance(source_conn, SSHConnection):
            for container in job_config.get('containers', []):
                source_conn.execute_command(f"docker start {container}")
       
        source_conn.disconnect()
        dest_conn.disconnect()
       
        duration = time.time() - start_time
       
        if success:
            # Apply retention with remote cleanup
            retention_days = job_config.get('retention_days', 30)
            retention_count = job_config.get('retention_count', 5)
            apply_retention(data_dir, job_name, retention_days, retention_count,
                          dest_server, destination_path)
           
            status_queue.put({
                'job_id': job_id,
                'status': 'completed',
                'progress': 100,
                'message': 'Backup completed',
                'completed_at': datetime.now().isoformat()
            })
           
            source_paths_str = ", ".join(source_paths[:3])
            if len(source_paths) > 3:
                source_paths_str += f" +{len(source_paths)-3} more"
           
            backup_fanout_notify(
                job_id=job_id,
                job_name=job_name,
                status='success',
                source_path=source_paths_str,
                dest_path=destination_path,
                duration=duration
            )
        else:
            raise Exception("Backup failed during execution")
           
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        logger.error(f"Backup failed: {error_msg}\n{error_trace}")
       
        duration = time.time() - start_time
       
        status_queue.put({
            'job_id': job_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Backup failed: {error_msg}',
            'failed_at': datetime.now().isoformat()
        })
       
        try:
            source_paths = job_config.get('paths') or job_config.get('source_paths', [])
            source_paths_str = ", ".join(source_paths[:3])
            if len(source_paths) > 3:
                source_paths_str += f" +{len(source_paths)-3} more"
           
            backup_fanout_notify(
                job_id=job_id,
                job_name=job_config.get('name', 'Unknown Job'),
                status='failed',
                source_path=source_paths_str,
                dest_path=job_config.get('destination_path'),
                duration=duration,
                error=error_msg
            )
        except:
            pass

def perform_sync_mode(source_conn, dest_conn, source_paths, dest_path, status_queue, job_id,
                     job_archive_dir, timestamp):
    """Live rsync mirroring mode"""
    try:
        for idx, source_path in enumerate(source_paths):
            progress = 30 + (idx * 60 // len(source_paths))
            status_queue.put({
                'job_id': job_id,
                'status': 'running',
                'progress': progress,
                'message': f'Syncing {source_path}...'
            })
           
            if isinstance(source_conn, SSHConnection) and isinstance(dest_conn, SSHConnection):
                temp_dir = tempfile.mkdtemp(prefix='jarvis_sync_')
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
            else:
                source_full = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                dest_full = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'), os.path.basename(source_path))
                sync_directories(source_full, dest_full)
        return True
    except Exception as e:
        status_queue.put({
            'job_id': job_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Sync failed: {str(e)}'
        })
        raise

def perform_full_backup(source_conn, dest_conn, source_paths, dest_path, compress,
                       status_queue, job_id, job_archive_dir, timestamp,
                       job_config, data_dir):
    """Perform full backup with job_name/timestamp/ subfolder structure"""
    try:
        # Create timestamped subfolder inside job folder
        job_subfolder = job_archive_dir / timestamp
        os.makedirs(job_subfolder, exist_ok=True)
        logger.info(f"Created local backup folder: {job_subfolder}")
        
        temp_data_dir = tempfile.mkdtemp(prefix='jarvis_backup_tmp_')
        
        for idx, source_path in enumerate(source_paths):
            progress = 30 + (idx * 40 // len(source_paths))
            status_queue.put({
                'job_id': job_id,
                'status': 'running',
                'progress': progress,
                'message': f'Copying {source_path}...'
            })
            dest_local = Path(temp_data_dir) / os.path.basename(source_path.strip('/'))
            if isinstance(source_conn, SSHConnection):
                download_via_rsync(source_conn, source_path, str(dest_local))
            else:
                source_full = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                shutil.copytree(source_full, dest_local, dirs_exist_ok=True)
        
        archive_path = job_subfolder / f'backup_{timestamp}.tar.gz'
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 75,
            'message': 'Compressing archive...'
        })
        
        with tarfile.open(archive_path, "w:gz") as tar:
            for root, dirs, files in os.walk(temp_data_dir):
                for name in files:
                    item_path = os.path.join(root, name)
                    rel_path = os.path.relpath(item_path, temp_data_dir)
                    safe_add(tar, item_path, arcname=rel_path)
            tar.close()
        
        size_mb = archive_path.stat().st_size / (1024 * 1024)
       
        # Upload archive to remote in job_name/timestamp/ structure
        job_name = job_config.get('name', 'Unknown Job').replace(' ', '_')
        remote_job_folder = f"{dest_path.rstrip('/')}/{job_name}/{timestamp}"
       
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 85,
            'message': f'Uploading to {remote_job_folder}...'
        })
        
        if isinstance(dest_conn, SSHConnection):
            # Create remote folder structure: dest_path/job_name/timestamp/
            create_cmd = f"mkdir -p '{remote_job_folder}'"
            stdout, stderr = dest_conn.execute_command(create_cmd)
            if stderr:
                logger.error(f"Failed to create remote folder: {stderr}")
                raise Exception(f"Failed to create remote folder: {stderr}")
            logger.info(f"Created remote folder: {remote_job_folder}")
            
            # Upload the tar.gz file
            remote_archive_path = f"{remote_job_folder}/backup_{timestamp}.tar.gz"
            dest_conn.sftp.put(str(archive_path), remote_archive_path)
            logger.info(f"Uploaded to remote: {remote_archive_path}")
        elif hasattr(dest_conn, "mount_point"):
            remote_full = os.path.join(dest_conn.mount_point, remote_job_folder.lstrip('/'))
            os.makedirs(remote_full, exist_ok=True)
            shutil.copy2(archive_path, remote_full)
            logger.info(f"Copied to remote mount: {remote_full}/backup_{timestamp}.tar.gz")
        else:
            logger.warning("Unknown destination type: archive not uploaded")
       
        archive_id = str(uuid.uuid4())
        duration = time.time() - job_config['start_time']
        create_archive_record(archive_id, job_id, job_config, duration, archive_path, size_mb, data_dir)
        shutil.rmtree(temp_data_dir, ignore_errors=True)
        return True
    except Exception as e:
        raise Exception(f"Full backup failed: {str(e)}") from e

def perform_incremental_backup(source_conn, dest_conn, source_paths, dest_path,
                              status_queue, job_id, job_archive_dir):
    """Perform incremental backup"""
    try:
        for idx, source_path in enumerate(source_paths):
            progress = 30 + (idx * 60 // len(source_paths))
            status_queue.put({
                'job_id': job_id,
                'status': 'running',
                'progress': progress,
                'message': f'Updating {source_path}...'
            })
           
            if isinstance(source_conn, SSHConnection) and isinstance(dest_conn, SSHConnection):
                temp_dir = tempfile.mkdtemp(prefix='jarvis_sync_')
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
            else:
                source_full = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                dest_full = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'), os.path.basename(source_path))
                sync_directories(source_full, dest_full)
        return True
    except Exception as e:
        raise Exception(f"Incremental backup failed: {str(e)}") from e

def download_via_rsync(ssh_conn, remote_path, local_path, incremental=False):
    """Download using rsync"""
    os.makedirs(local_path, exist_ok=True)
    try:
        subprocess.run(['which', 'rsync'], check=True, capture_output=True)
        subprocess.run(['which', 'sshpass'], check=True, capture_output=True)
        has_rsync = True
    except:
        has_rsync = False
   
    if not has_rsync:
        download_via_sftp(ssh_conn, remote_path, local_path)
        return
   
    cmd = [
        'rsync', '-avz', '--progress',
        '-e', f'sshpass -p "{ssh_conn.password}" ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}',
        f'{ssh_conn.username}@{ssh_conn.host}:{remote_path}/', local_path + '/'
    ]
    if incremental:
        cmd.insert(2, '--update')
    subprocess.run(cmd, check=True)

def download_via_sftp(ssh_conn, remote_path, local_path):
    """Fallback SFTP download"""
    import stat
    try:
        remote_stat = ssh_conn.sftp.stat(remote_path)
        if stat.S_ISDIR(remote_stat.st_mode):
            os.makedirs(local_path, exist_ok=True)
            for item in ssh_conn.sftp.listdir_attr(remote_path):
                r_item = os.path.join(remote_path, item.filename)
                l_item = os.path.join(local_path, item.filename)
                if stat.S_ISDIR(item.st_mode):
                    download_via_sftp(ssh_conn, r_item, l_item)
                else:
                    ssh_conn.sftp.get(r_item, l_item)
        else:
            ssh_conn.sftp.get(remote_path, os.path.join(local_path, os.path.basename(remote_path)))
    except Exception as e:
        raise Exception(f"SFTP download failed: {e}")

def upload_via_rsync(ssh_conn, local_path, remote_path):
    """Upload using rsync"""
    try:
        subprocess.run(['which', 'rsync'], check=True, capture_output=True)
        subprocess.run(['which', 'sshpass'], check=True, capture_output=True)
        has_rsync = True
    except:
        has_rsync = False
   
    if not has_rsync:
        upload_via_sftp(ssh_conn, local_path, remote_path)
        return
   
    cmd = [
        'rsync', '-avz', '--progress',
        '-e', f'sshpass -p "{ssh_conn.password}" ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}',
        local_path + ('/' if os.path.isdir(local_path) else ''),
        f'{ssh_conn.username}@{ssh_conn.host}:{remote_path}/'
    ]
    subprocess.run(cmd, check=True)

def upload_via_sftp(ssh_conn, local_path, remote_path):
    """Fallback SFTP upload"""
    import stat
    try:
        try:
            ssh_conn.sftp.stat(remote_path)
        except:
            ssh_conn.sftp.mkdir(remote_path)
       
        if os.path.isdir(local_path):
            for item in os.listdir(local_path):
                l_item = os.path.join(local_path, item)
                r_item = os.path.join(remote_path, item)
                if os.path.isdir(l_item):
                    upload_via_sftp(ssh_conn, l_item, r_item)
                else:
                    ssh_conn.sftp.put(l_item, r_item)
        else:
            ssh_conn.sftp.put(local_path, os.path.join(remote_path, os.path.basename(local_path)))
    except Exception as e:
        raise Exception(f"SFTP upload failed: {e}")

def sync_directories(source, dest):
    """Sync directories incrementally"""
    os.makedirs(dest, exist_ok=True)
    for root, dirs, files in os.walk(source):
        rel_path = os.path.relpath(root, source)
        dest_root = os.path.join(dest, rel_path) if rel_path != '.' else dest
        os.makedirs(dest_root, exist_ok=True)
        for file in files:
            s_file = os.path.join(root, file)
            d_file = os.path.join(dest_root, file)
            if not os.path.exists(d_file) or os.path.getmtime(s_file) > os.path.getmtime(d_file):
                shutil.copy2(s_file, d_file)

def restore_worker(restore_id: str, restore_config: Dict, status_queue: Queue):
    """Worker for restore operations"""
    start_time = time.time()
    temp_dir = None
   
    try:
        logger.info(f"Restore worker started for {restore_id}")
        archive = restore_config['archive']
        dest_server_id = restore_config['dest_server_id']
        dest_path = restore_config.get('dest_path')
        restore_to_original = dest_path in [None, '', 'original']
        data_dir = Path(restore_config['_data_dir'])
       
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 10,
            'message': 'Loading configuration...'
        })
       
        servers_file = data_dir / 'backup_servers.json'
        with open(servers_file, 'r') as f:
            all_servers = json.load(f)
       
        source_server_id = archive.get('dest_server_id')
        source_server = next((s for s in all_servers if s['id'] == source_server_id), None)
        if not source_server:
            raise Exception("Backup storage server not found")
       
        # Use source_server_id from archive when restoring to original
        if restore_to_original:
            original_source_server_id = archive.get('source_server_id')
            if not original_source_server_id:
                raise Exception("Cannot restore to original: source_server_id not found in archive")
            dest_server = next((s for s in all_servers if s['id'] == original_source_server_id), None)
            if not dest_server:
                raise Exception(f"Original source server '{original_source_server_id}' not found")
            logger.info(f"Restoring to original source server: {dest_server.get('name')}")
        else:
            dest_server = next((s for s in all_servers if s['id'] == dest_server_id), None)
            if not dest_server:
                raise Exception("Restore destination not found")
       
        archive_path = Path(archive['archive_path'])
        if not archive_path.exists():
            raise Exception(f"Archive not found: {archive_path}")
       
        if not verify_tar_integrity(archive_path):
            raise Exception("Archive is corrupted")
       
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 30,
            'message': 'Connecting to source...'
        })
       
        source_conn = create_connection(source_server['type'], **source_server)
        if not source_conn.connect():
            raise Exception("Failed to connect to backup storage")
       
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 50,
            'message': 'Connecting to destination...'
        })
       
        dest_conn = create_connection(dest_server['type'], **dest_server)
        if not dest_conn.connect():
            source_conn.disconnect()
            raise Exception("Failed to connect to restore destination")
       
        temp_dir = tempfile.mkdtemp(prefix='jarvis_restore_')
       
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 60,
            'message': 'Extracting archive...'
        })
       
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=temp_dir)
       
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 80,
            'message': 'Restoring files...'
        })
       
        if restore_to_original:
            source_paths = archive.get('source_paths', [])
            if not source_paths:
                raise Exception("No source paths stored for restore-to-original mode.")
            for src in source_paths:
                logger.info(f"Restoring to original path: {src}")
                if isinstance(dest_conn, SSHConnection):
                    upload_via_sftp(dest_conn, temp_dir, src)
                else:
                    dest_full = os.path.join(dest_conn.mount_point, src.lstrip('/'))
                    os.makedirs(dest_full, exist_ok=True)
                    for item in os.listdir(temp_dir):
                        s_item = os.path.join(temp_dir, item)
                        if os.path.isdir(s_item):
                            shutil.copytree(s_item, dest_full, dirs_exist_ok=True)
                        else:
                            shutil.copy2(s_item, dest_full)
        else:
            if isinstance(dest_conn, SSHConnection):
                upload_via_sftp(dest_conn, temp_dir, dest_path)
            else:
                dest_full = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'))
                os.makedirs(dest_full, exist_ok=True)
                for item in os.listdir(temp_dir):
                    src = os.path.join(temp_dir, item)
                    dst = os.path.join(dest_full, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
       
        source_conn.disconnect()
        dest_conn.disconnect()
       
        duration = time.time() - start_time
       
        status_queue.put({
            'restore_id': restore_id,
            'status': 'completed',
            'progress': 100,
            'message': f'Restore completed in {duration:.1f}s',
            'completed_at': datetime.now().isoformat()
        })
       
        backup_fanout_notify(
            job_id=restore_id,
            job_name=archive.get('job_name', 'Restore'),
            status='success',
            dest_path=dest_path if dest_path else 'original location',
            duration=duration,
            restore=True
        )
       
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        status_queue.put({
            'restore_id': restore_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Restore failed: {str(e)}',
            'failed_at': datetime.now().isoformat()
        })
        backup_fanout_notify(
            job_id=restore_id,
            job_name=archive.get('job_name', 'Restore'),
            status='failed',
            error=str(e),
            restore=True
        )
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

class BackupManager:
    """Main backup manager"""
   
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.data_dir / 'backup_jobs.json'
        self.status_file = self.data_dir / 'backup_status.json'
        self.jobs = self._load_jobs()
        self.statuses = self._load_statuses()
        self.worker_processes = {}
        self.status_updater = None
        self.servers = {s['id']: s for s in self.get_all_servers()}
       
    def _load_jobs(self):
        if self.jobs_file.exists():
            with open(self.jobs_file, 'r') as f:
                return json.load(f)
        return {}
       
    def _save_jobs(self):
        with open(self.jobs_file, 'w') as f:
            json.dump(self.jobs, f, indent=2)
           
    def _load_statuses(self):
        if self.status_file.exists():
            with open(self.status_file, 'r') as f:
                return json.load(f)
        return {}
       
    def _save_statuses(self):
        with open(self.status_file, 'w') as f:
            json.dump(self.statuses, f, indent=2)
           
    async def start(self):
        self.status_updater = asyncio.create_task(self._status_updater())
        logger.info("Backup manager started")
       
    async def stop(self):
        if self.status_updater:
            self.status_updater.cancel()
        for process in self.worker_processes.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        logger.info("Backup manager stopped")
       
    async def _status_updater(self):
        while True:
            try:
                while not status_queue.empty():
                    update = status_queue.get_nowait()
                    key = update.get('job_id') or update.get('restore_id')
                    if key not in self.statuses:
                        self.statuses[key] = {}
                    self.statuses[key].update(update)
                    self._save_statuses()
                finished = [k for k, p in self.worker_processes.items() if not p.is_alive()]
                for k in finished:
                    del self.worker_processes[k]
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Status updater error: {e}")
                await asyncio.sleep(1)
               
    def create_job(self, job_config: Dict) -> str:
        job_id = str(uuid.uuid4())
        job_config['id'] = job_id
        job_config['created_at'] = datetime.now().isoformat()
        self.jobs[job_id] = job_config
        self._save_jobs()
        return job_id
       
    def run_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        if job_id in self.worker_processes and self.worker_processes[job_id].is_alive():
            return False
        job_config = self.jobs[job_id].copy()
        job_config['_data_dir'] = str(self.data_dir)
        process = Process(target=backup_worker, args=(job_id, job_config, status_queue))
        process.start()
        self.worker_processes[job_id] = process
        self.statuses[job_id] = {
            'job_id': job_id, 'status': 'queued', 'progress': 0,
            'message': 'Job queued', 'started_at': datetime.now().isoformat()
        }
        self._save_statuses()
        return True
       
    def get_job_status(self, job_id: str) -> Dict:
        return self.statuses.get(job_id, {})
       
    def get_all_jobs(self) -> Dict:
        return self.jobs
       
    def delete_job(self, job_id: str) -> bool:
        """Delete a job and all its backups from both local and remote storage"""
        job = self.jobs.get(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found.")
            return False

        job_name = job.get("name", f"job_{job_id}")
        dest_server_id = job.get("destination_server_id")
        dest_path = job.get("destination_path")

        # Delete from remote destination server
        if dest_server_id and dest_path:
            dest_server = self.servers.get(dest_server_id)
            if dest_server:
                try:
                    logger.info(f"Connecting to destination server to delete backups for job {job_name}")
                    dest_conn = create_connection(dest_server['type'], **dest_server)
                    if dest_conn.connect():
                        remote_job_folder = f"{dest_path.rstrip('/')}/{job_name}"
                        delete_remote_directory(dest_conn, remote_job_folder)
                        dest_conn.disconnect()
                        logger.info(f"Deleted remote job folder: {remote_job_folder}")
                    else:
                        logger.error(f"Failed to connect to destination server for deletion")
                except Exception as e:
                    logger.error(f"Failed to delete remote backups for {job_name}: {e}")
            else:
                logger.warning(f"Destination server not found for job {job_id}")

        # Delete local metadata
        self.jobs.pop(job_id, None)
        self._save_jobs()

        if job_id in self.statuses:
            del self.statuses[job_id]
            self._save_statuses()

        # Delete local archive folder
        local_dir = get_job_archive_dir(self.data_dir, job_name)
        if local_dir.exists():
            try:
                shutil.rmtree(local_dir)
                logger.info(f"Deleted local archive folder: {local_dir}")
            except Exception as e:
                logger.error(f"Failed to delete local archive folder {local_dir}: {e}")

        # Remove archives from backup_archives.json
        archives_file = self.data_dir / 'backup_archives.json'
        if archives_file.exists():
            with open(archives_file, 'r') as f:
                all_archives = json.load(f)
            filtered_archives = [a for a in all_archives if a.get('job_id') != job_id]
            with open(archives_file, 'w') as f:
                json.dump(filtered_archives, f, indent=2)

        return True
   
    def get_all_servers(self) -> List[Dict]:
        servers_file = self.data_dir / 'backup_servers.json'
        if servers_file.exists():
            with open(servers_file, 'r') as f:
                return json.load(f)
        return []
   
    def add_server(self, server_config: Dict) -> str:
        server_id = str(uuid.uuid4())
        server_config['id'] = server_id
        servers = self.get_all_servers()
        servers.append(server_config)
        with open(self.data_dir / 'backup_servers.json', 'w') as f:
            json.dump(servers, f, indent=2)
        self.servers[server_id] = server_config
        return server_id
   
    def delete_server(self, server_id: str) -> bool:
        servers = self.get_all_servers()
        filtered = [s for s in servers if s.get('id') != server_id]
        if len(filtered) < len(servers):
            with open(self.data_dir / 'backup_servers.json', 'w') as f:
                json.dump(filtered, f, indent=2)
            self.servers.pop(server_id, None)
            return True
        return False
   
    def get_all_archives(self) -> List[Dict]:
        archives_file = self.data_dir / 'backup_archives.json'
        if archives_file.exists():
            with open(archives_file, 'r') as f:
                return json.load(f)
        return []
   
    def delete_archive(self, archive_id: str) -> bool:
        archives = self.get_all_archives()
        archive = next((a for a in archives if a.get('id') == archive_id), None)
        if not archive:
            logger.error(f"Archive {archive_id} not found")
            return False
       
        # Delete from remote destination FIRST
        dest_server_id = archive.get('dest_server_id')
        if dest_server_id:
            dest_server = self.servers.get(dest_server_id)
            if dest_server:
                dest_conn = None
                try:
                    logger.info(f"Connecting to remote to delete archive {archive_id}")
                    dest_conn = create_connection(dest_server['type'], **dest_server)
                    if dest_conn.connect():
                        # Extract timestamp from archive path
                        archive_path = Path(archive['archive_path'])
                        timestamp = archive_path.parent.name
                        job_name = archive.get('job_name', 'Unknown').replace(' ', '_')
                        dest_path = archive.get('destination_path', '')
                       
                        remote_folder = f"{dest_path.rstrip('/')}/{job_name}/{timestamp}"
                        logger.info(f"Deleting remote folder: {remote_folder}")
                        
                        if isinstance(dest_conn, SSHConnection):
                            stdout, stderr = dest_conn.execute_command(f"rm -rf '{remote_folder}'")
                            if stderr and "No such file" not in stderr:
                                logger.error(f"Remote delete stderr: {stderr}")
                            else:
                                logger.info(f"Deleted remote archive folder: {remote_folder}")
                        elif isinstance(dest_conn, (SMBConnection, NFSConnection)):
                            full_path = os.path.join(dest_conn.mount_point, remote_folder.lstrip('/'))
                            if os.path.exists(full_path):
                                shutil.rmtree(full_path)
                                logger.info(f"Deleted remote archive folder: {full_path}")
                            else:
                                logger.warning(f"Remote path doesn't exist: {full_path}")
                        
                        dest_conn.disconnect()
                    else:
                        logger.error(f"Failed to connect to destination server")
                except Exception as e:
                    logger.error(f"Failed to delete remote archive: {e}", exc_info=True)
                finally:
                    if dest_conn and dest_conn.connected:
                        dest_conn.disconnect()
            else:
                logger.warning(f"Destination server {dest_server_id} not found in servers list")
       
        # Delete local folder (entire timestamp folder)
        if archive and Path(archive['archive_path']).exists():
            try:
                archive_path = Path(archive['archive_path'])
                timestamp_folder = archive_path.parent
                
                # Delete entire timestamp folder
                if timestamp_folder.exists():
                    shutil.rmtree(timestamp_folder)
                    logger.info(f"Deleted local archive folder: {timestamp_folder}")
            except Exception as e:
                logger.error(f"Failed to delete local archive folder: {e}")
       
        # Remove from JSON
        filtered = [a for a in archives if a.get('id') != archive_id]
        with open(self.data_dir / 'backup_archives.json', 'w') as f:
            json.dump(filtered, f, indent=2)
        
        logger.info(f"Archive {archive_id} deleted successfully")
        return True
   
    def start_restore(self, archive_id: str, dest_server_id: str, dest_path: str,
                     selective_items: list = None) -> str:
        archives = self.get_all_archives()
        archive = next((a for a in archives if a['id'] == archive_id), None)
        if not archive:
            raise Exception("Archive not found")
       
        restore_id = str(uuid.uuid4())
        restore_config = {
            'restore_id': restore_id,
            'archive': archive,
            'dest_server_id': dest_server_id,
            'dest_path': dest_path,
            'selective_items': selective_items or [],
            '_data_dir': str(self.data_dir)
        }
       
        process = Process(target=restore_worker, args=(restore_id, restore_config, status_queue))
        process.start()
        self.worker_processes[restore_id] = process
       
        self.statuses[restore_id] = {
            'restore_id': restore_id, 'status': 'queued', 'progress': 0,
            'message': 'Restore queued', 'started_at': datetime.now().isoformat()
        }
        self._save_statuses()
        return restore_id

    def get_restore_status(self, restore_id: str) -> Dict:
        """Get restore status"""
        return self.statuses.get(restore_id, {})

    def import_archives(self):
        """Import existing .tar.gz files"""
        return import_existing_archives(self.data_dir)

backup_manager = None

async def init_backup_module(app):
    global backup_manager
    data_dir = app.get('data_dir', '/data') + '/backup_module'
    backup_manager = BackupManager(data_dir)
    await backup_manager.start()

async def cleanup_backup_module(app):
    global backup_manager
    if backup_manager:
        await backup_manager.stop()

async def test_connection(request):
    try:
        data = await request.json()
        conn = create_connection(data['type'], **data)
        success = conn.connect()
        conn.disconnect()
        return web.json_response({'success': success, 'message': 'Connection successful' if success else 'Connection failed'})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def browse_directory(request):
    try:
        data = await request.json()
        server_config = data.get('server_config') or data.get('connection')
        if not server_config:
            return web.json_response({'success': False, 'message': 'No server config'}, status=400)
        conn = create_connection(server_config['type'], **server_config)
        if not conn.connect():
            return web.json_response({'success': False, 'message': 'Connection failed'}, status=400)
        items = conn.list_directory(data.get('path', '/'))
        conn.disconnect()
        return web.json_response({'success': True, 'files': items})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def create_backup_job(request):
    try:
        data = await request.json()
        job_id = backup_manager.create_job(data)
        return web.json_response({'success': True, 'job_id': job_id})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def run_backup_job(request):
    try:
        job_id = request.match_info['job_id']
        success = backup_manager.run_job(job_id)
        return web.json_response({'success': success, 'message': 'Job started' if success else 'Failed'})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def get_job_status(request):
    try:
        job_id = request.match_info['job_id']
        status = backup_manager.get_job_status(job_id)
        return web.json_response({'success': True, 'status': status})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def get_all_jobs(request):
    try:
        jobs = list(backup_manager.get_all_jobs().values())
        return web.json_response({'jobs': jobs})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def delete_backup_job(request):
    try:
        job_id = request.match_info['job_id']
        success = backup_manager.delete_job(job_id)
        return web.json_response({'success': success, 'message': 'Job deleted' if success else 'Not found'})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def get_servers(request):
    try:
        servers = backup_manager.get_all_servers()
        return web.json_response({
            'source_servers': [s for s in servers if s.get('server_type') == 'source'],
            'destination_servers': [s for s in servers if s.get('server_type') == 'destination']
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def add_server(request):
    try:
        data = await request.json()
        server_id = backup_manager.add_server(data)
        return web.json_response({'success': True, 'id': server_id})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def delete_server(request):
    try:
        server_id = request.match_info['server_id']
        success = backup_manager.delete_server(server_id)
        return web.json_response({'success': success})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def get_archives(request):
    try:
        archives = backup_manager.get_all_archives()
        return web.json_response({'archives': archives})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def delete_archive(request):
    try:
        archive_id = request.match_info['archive_id']
        success = backup_manager.delete_archive(archive_id)
        return web.json_response({'success': success})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def restore_backup(request):
    try:
        data = await request.json()
        restore_id = backup_manager.start_restore(
            data['archive_id'],
            data['destination_server_id'],
            data.get('destination_path', ''),
            data.get('selective_items', [])
        )
        return web.json_response({'success': True, 'restore_id': restore_id})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def get_restore_status(request):
    """Get restore status"""
    try:
        restore_id = request.match_info['restore_id']
        status = backup_manager.get_restore_status(restore_id)
        return web.json_response({'success': True, 'status': status})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def import_archives(request):
    try:
        count = backup_manager.import_archives()
        return web.json_response({'success': True, 'imported': count})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

def setup_routes(app):
    app.router.add_post('/api/backup/jobs', create_backup_job)
    app.router.add_get('/api/backup/jobs', get_all_jobs)
    app.router.add_post('/api/backup/jobs/{job_id}/run', run_backup_job)
    app.router.add_get('/api/backup/jobs/{job_id}/status', get_job_status)
    app.router.add_delete('/api/backup/jobs/{job_id}', delete_backup_job)
   
    app.router.add_get('/api/backup/servers', get_servers)
    app.router.add_post('/api/backup/servers', add_server)
    app.router.add_delete('/api/backup/servers/{server_id}', delete_server)
   
    app.router.add_get('/api/backup/archives', get_archives)
    app.router.add_delete('/api/backup/archives/{archive_id}', delete_archive)
    app.router.add_post('/api/backup/import-archives', import_archives)
   
    app.router.add_post('/api/backup/test-connection', test_connection)
    app.router.add_post('/api/backup/browse', browse_directory)
    app.router.add_post('/api/backup/restore', restore_backup)
    app.router.add_get('/api/backup/restore/{restore_id}/status', get_restore_status)
   
    app.on_startup.append(init_backup_module)
    app.on_cleanup.append(cleanup_backup_module)
