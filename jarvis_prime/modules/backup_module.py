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
from datetime import datetime
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
                         error: str = None):
    """
    Fan-out detailed backup job notification through Jarvis Prime's multi-channel system.
    """
    try:
        import sys
        import textwrap
        
        # Add parent directory to path to import bot
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        
        from bot import process_incoming
        
        # Build message
        emoji = "✅" if status == "success" else "❌"
        title = f"{emoji} Backup {job_name}"
        
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
        logger.info(f"Backup notification sent for job {job_id}")
        
    except Exception as e:
        # Fallback to error notification if available
        try:
            from errors import notify_error
            notify_error(f"[Backup Fanout Failure] {str(e)}", context="backup")
        except Exception:
            logger.error(f"Backup fanout failed: {e}")


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
        attrs = self.sftp.listdir_attr(path)
        
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
        # Check if rsync exists
        stdout, stderr = ssh_conn.execute_command('which rsync')
        if stdout.strip():
            return True  # rsync already installed
        
        logger.info(f"rsync not found on {ssh_conn.host}, attempting to install...")
        
        # Try to install rsync
        install_cmd = 'sudo apt-get update && sudo apt-get install -y rsync || yum install -y rsync'
        stdout, stderr = ssh_conn.execute_command(install_cmd)
        
        # Verify installation
        stdout, stderr = ssh_conn.execute_command('which rsync')
        if stdout.strip():
            logger.info(f"Successfully installed rsync on {ssh_conn.host}")
            return True
        else:
            logger.warning(f"Failed to auto-install rsync on {ssh_conn.host}: {stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking/installing rsync: {e}")
        return False


def create_archive_record(job_id: str, job_config: Dict, duration: float, data_dir: Path):
    """Create archive record after successful backup"""
    import json
    from pathlib import Path
    
    archives_file = Path(data_dir) / 'backup_archives.json'
    
    # Load existing archives
    if archives_file.exists():
        with open(archives_file, 'r') as f:
            archives = json.load(f)
    else:
        archives = []
    
    # Create new archive record
    archive_id = str(uuid.uuid4())
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
        'size_mb': 0,  # TODO: Calculate actual size
        'created_at': timestamp.isoformat(),
        'duration': duration,
        'status': 'completed'
    }
    
    archives.append(archive)
    
    # Save archives
    with open(archives_file, 'w') as f:
        json.dump(archives, f, indent=2)
    
    logger.info(f"Created archive record {archive_id} for job {job_id}")


def backup_worker(job_id: str, job_config: Dict, status_queue: Queue):
    """
    Worker function that runs in separate process
    Performs the actual backup operation
    """
    start_time = time.time()
    job_config['start_time'] = start_time
    
    try:
        logger.info(f"Backup worker started for job {job_id}")
        
        # Load server configurations
        import json
        from pathlib import Path
        
        # Get data_dir from job config (passed by parent process)
        data_dir = Path(job_config.get('_data_dir', '/data/backup_module'))
        servers_file = data_dir / 'backup_servers.json'
        
        if not servers_file.exists():
            raise Exception(f"No servers configured. Please add source and destination servers. Looking in: {servers_file}")
        
        with open(servers_file, 'r') as f:
            all_servers = json.load(f)
        
        # Find source server
        source_server_id = job_config.get('source_server_id')
        if not source_server_id:
            raise Exception("No source server specified in job configuration")
        
        source_server = next((s for s in all_servers if s.get('id') == source_server_id), None)
        if not source_server:
            raise Exception(f"Source server '{source_server_id}' not found. Server may have been deleted.")
        
        # Find destination server  
        dest_server_id = job_config.get('destination_server_id')
        if not dest_server_id:
            raise Exception("No destination server specified in job configuration")
            
        dest_server = next((s for s in all_servers if s.get('id') == dest_server_id), None)
        if not dest_server:
            raise Exception(f"Destination server '{dest_server_id}' not found. Server may have been deleted.")
        
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 0,
            'message': f'Connecting to source: {source_server["name"]} ({source_server["host"]})...'
        })
        
        source_conn = create_connection(
            source_server['type'],
            **source_server
        )
        
        if not source_conn.connect():
            raise Exception(f"Failed to connect to source server {source_server['name']} at {source_server['host']}. Check credentials and network connectivity.")
        
        # Ensure rsync is installed on SSH servers
        if isinstance(source_conn, SSHConnection):
            ensure_rsync_installed(source_conn)
            
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 10,
            'message': f'Connected to source. Connecting to destination: {dest_server["name"]} ({dest_server["host"]})...'
        })
        
        dest_conn = create_connection(
            dest_server['type'],
            **dest_server
        )
        
        if not dest_conn.connect():
            source_conn.disconnect()
            raise Exception(f"Failed to connect to destination server {dest_server['name']} at {dest_server['host']}. Check credentials and network connectivity.")
        
        # Ensure rsync is installed on destination SSH server
        if isinstance(dest_conn, SSHConnection):
            ensure_rsync_installed(dest_conn)
            
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 20,
            'message': 'Connected to destination, starting backup...'
        })
        
        # Stop containers if requested
        if job_config.get('stop_containers') and isinstance(source_conn, SSHConnection):
            for container in job_config.get('containers', []):
                source_conn.execute_command(f"docker stop {container}")
                time.sleep(2)
            
        # Perform backup
        backup_type = job_config.get('backup_type', 'incremental')
        compress = job_config.get('compress', True)
        source_paths = job_config.get('paths') or job_config.get('source_paths', [])
        
        if not source_paths:
            raise Exception("No source paths specified. Please select folders/files to backup.")
        
        destination_path = job_config.get('destination_path', '/backups')
        
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 25,
            'message': f'Backing up {len(source_paths)} items...'
        })
        
        if backup_type == 'full':
            success = perform_full_backup(
                source_conn,
                dest_conn,
                source_paths,
                destination_path,
                compress,
                status_queue,
                job_id
            )
        else:
            success = perform_incremental_backup(
                source_conn,
                dest_conn,
                source_paths,
                destination_path,
                compress,
                status_queue,
                job_id
            )
            
        # Start containers if we stopped them
        if job_config.get('stop_containers') and isinstance(source_conn, SSHConnection):
            for container in job_config.get('containers', []):
                source_conn.execute_command(f"docker start {container}")
            
        # Cleanup
        source_conn.disconnect()
        dest_conn.disconnect()
        
        # Calculate duration
        duration = time.time() - job_config.get('start_time', time.time())
        
        # Backup functions now raise exceptions on failure, so if we get here it succeeded
        status_queue.put({
            'job_id': job_id,
            'status': 'completed',
            'progress': 100,
            'message': 'Backup completed successfully',
            'completed_at': datetime.now().isoformat()
        })
        
        # CREATE ARCHIVE RECORD
        try:
            data_dir_path = Path(job_config.get('_data_dir', '/data/backup_module'))
            create_archive_record(job_id, job_config, duration, data_dir_path)
        except Exception as archive_error:
            logger.error(f"Failed to create archive record: {archive_error}")
        
        # Send success notification
        try:
            source_paths = job_config.get('paths') or job_config.get('source_paths', [])
            source_paths_str = ", ".join(source_paths[:3])
            if len(source_paths) > 3:
                source_paths_str += f" +{len(source_paths) - 3} more"
            
            backup_fanout_notify(
                job_id=job_id,
                job_name=job_config.get('name', 'Unknown Job'),
                status='success',
                source_path=source_paths_str,
                dest_path=job_config.get('destination_path'),
                duration=duration
            )
        except Exception as notify_error:
            logger.error(f"Failed to send success notification: {notify_error}")
            
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        
        logger.error(f"Backup worker failed for job {job_id}: {error_msg}")
        logger.error(f"Full traceback:\n{error_trace}")
        
        duration = time.time() - job_config.get('start_time', time.time())
        
        status_queue.put({
            'job_id': job_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Backup failed: {error_msg}',
            'failed_at': datetime.now().isoformat()
        })
        
        # Send failure notification
        try:
            source_paths = job_config.get('paths') or job_config.get('source_paths', [])
            source_paths_str = ", ".join(source_paths[:3])
            if len(source_paths) > 3:
                source_paths_str += f" +{len(source_paths) - 3} more"
            
            backup_fanout_notify(
                job_id=job_id,
                job_name=job_config.get('name', 'Unknown Job'),
                status='failed',
                source_path=source_paths_str,
                dest_path=job_config.get('destination_path'),
                duration=duration,
                error=error_msg
            )
        except Exception as notify_error:
            logger.error(f"Failed to send failure notification: {notify_error}")


def perform_full_backup(source_conn, dest_conn, source_paths, dest_path, compress, status_queue, job_id):
    """Perform full backup"""
    try:
        temp_dir = tempfile.mkdtemp(prefix='jarvis_backup_')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        for idx, source_path in enumerate(source_paths):
            progress = 30 + (idx * 40 // len(source_paths))
            status_queue.put({
                'job_id': job_id,
                'status': 'running',
                'progress': progress,
                'message': f'Backing up {source_path}...'
            })
            
            if isinstance(source_conn, SSHConnection):
                download_via_rsync(source_conn, source_path, temp_dir)
            else:
                source_full = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                dest_full = os.path.join(temp_dir, os.path.basename(source_path))
                shutil.copytree(source_full, dest_full, dirs_exist_ok=True)
                
        # Create archive if compression requested
        if compress:
            status_queue.put({
                'job_id': job_id,
                'status': 'running',
                'progress': 75,
                'message': 'Compressing backup...'
            })
            
            archive_name = f'backup_{timestamp}.tar.gz'
            archive_path = os.path.join(tempfile.gettempdir(), archive_name)
            
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(temp_dir, arcname=os.path.basename(temp_dir))
                
            shutil.rmtree(temp_dir)
            upload_file = archive_path
            is_archive = True
        else:
            upload_file = temp_dir
            is_archive = False
            
        # Upload to destination
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 85,
            'message': 'Uploading to destination...'
        })
        
        if isinstance(dest_conn, SSHConnection):
            if is_archive:
                # Upload archive file
                dest_full_path = os.path.join(dest_path, os.path.basename(upload_file))
                dest_conn.sftp.put(upload_file, dest_full_path)
            else:
                upload_via_rsync(dest_conn, upload_file, dest_path)
        else:
            dest_full_path = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'))
            os.makedirs(dest_full_path, exist_ok=True)
            
            if is_archive:
                shutil.copy2(upload_file, os.path.join(dest_full_path, os.path.basename(upload_file)))
            else:
                for item in os.listdir(upload_file):
                    src = os.path.join(upload_file, item)
                    dst = os.path.join(dest_full_path, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                
        # Cleanup
        if is_archive:
            os.remove(upload_file)
        else:
            shutil.rmtree(upload_file)
            
        return True
        
    except Exception as e:
        import traceback
        error_detail = f"Full backup failed: {str(e)}\nTraceback: {traceback.format_exc()}"
        logger.error(error_detail)
        
        # Put error in status queue
        status_queue.put({
            'job_id': job_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Backup failed: {str(e)}'
        })
        
        raise Exception(f"Full backup failed: {str(e)}") from e


def perform_incremental_backup(source_conn, dest_conn, source_paths, dest_path, compress, status_queue, job_id):
    """Perform incremental backup (only changed files)"""
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
                # Direct rsync between SSH hosts via local
                temp_dir = tempfile.mkdtemp(prefix='jarvis_sync_')
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
                
            elif isinstance(source_conn, SSHConnection):
                # SSH to mounted filesystem
                temp_dir = tempfile.mkdtemp(prefix='jarvis_sync_')
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                dest_full_path = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'), os.path.basename(source_path))
                sync_directories(temp_dir, dest_full_path)
                shutil.rmtree(temp_dir)
                
            elif isinstance(dest_conn, SSHConnection):
                # Mounted filesystem to SSH
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                temp_dir = tempfile.mkdtemp(prefix='jarvis_sync_')
                sync_directories(source_full_path, temp_dir)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
                
            else:
                # Between mounted filesystems
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                dest_full_path = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'), os.path.basename(source_path))
                sync_directories(source_full_path, dest_full_path)
                
        return True
        
    except Exception as e:
        import traceback
        error_detail = f"Incremental backup failed: {str(e)}\nTraceback: {traceback.format_exc()}"
        logger.error(error_detail)
        
        # Put error in status queue
        status_queue.put({
            'job_id': job_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Backup failed: {str(e)}'
        })
        
        raise Exception(f"Incremental backup failed: {str(e)}") from e


def download_via_rsync(ssh_conn, remote_path, local_path, incremental=False):
    """Download using rsync over SSH (with SFTP fallback)"""
    os.makedirs(local_path, exist_ok=True)
    
    # Check if rsync is available
    try:
        subprocess.run(['which', 'rsync'], check=True, capture_output=True)
        subprocess.run(['which', 'sshpass'], check=True, capture_output=True)
        has_rsync = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_rsync = False
    
    if not has_rsync:
        # Fallback to SFTP
        logger.warning("rsync not available, using SFTP fallback (slower)")
        download_via_sftp(ssh_conn, remote_path, local_path)
        return
    
    rsync_cmd = [
        'rsync',
        '-avz',
        '--progress',
        '-e', f'sshpass -p "{ssh_conn.password}" ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}',
        f'{ssh_conn.username}@{ssh_conn.host}:{remote_path}/',
        local_path + '/'
    ]
    
    if incremental:
        rsync_cmd.insert(2, '--update')
    
    try:
        result = subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_output = e.stderr if e.stderr else e.stdout
        raise Exception(f"rsync failed (exit code {e.returncode}): {error_output}")


def download_via_sftp(ssh_conn, remote_path, local_path):
    """Download using SFTP (slower but more compatible)"""
    import stat
    
    try:
        # Check if remote path exists and is a directory
        remote_stat = ssh_conn.sftp.stat(remote_path)
        
        if stat.S_ISDIR(remote_stat.st_mode):
            # Download directory recursively
            os.makedirs(local_path, exist_ok=True)
            
            for item in ssh_conn.sftp.listdir_attr(remote_path):
                remote_item = os.path.join(remote_path, item.filename)
                local_item = os.path.join(local_path, item.filename)
                
                if stat.S_ISDIR(item.st_mode):
                    # Recursively download subdirectory
                    download_via_sftp(ssh_conn, remote_item, local_item)
                else:
                    # Download file
                    ssh_conn.sftp.get(remote_item, local_item)
        else:
            # Download single file
            ssh_conn.sftp.get(remote_path, os.path.join(local_path, os.path.basename(remote_path)))
            
    except Exception as e:
        raise Exception(f"SFTP download failed: {str(e)}")


def upload_via_rsync(ssh_conn, local_path, remote_path):
    """Upload using rsync over SSH (with SFTP fallback)"""
    
    # Check if rsync is available
    try:
        subprocess.run(['which', 'rsync'], check=True, capture_output=True)
        subprocess.run(['which', 'sshpass'], check=True, capture_output=True)
        has_rsync = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_rsync = False
    
    if not has_rsync:
        # Fallback to SFTP
        logger.warning("rsync not available, using SFTP fallback (slower)")
        upload_via_sftp(ssh_conn, local_path, remote_path)
        return
    
    rsync_cmd = [
        'rsync',
        '-avz',
        '--progress',
        '-e', f'sshpass -p "{ssh_conn.password}" ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}',
        local_path + ('/' if os.path.isdir(local_path) else ''),
        f'{ssh_conn.username}@{ssh_conn.host}:{remote_path}/'
    ]
    
    try:
        result = subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_output = e.stderr if e.stderr else e.stdout
        raise Exception(f"rsync failed (exit code {e.returncode}): {error_output}")


def upload_via_sftp(ssh_conn, local_path, remote_path):
    """Upload using SFTP (slower but more compatible)"""
    import stat
    
    try:
        # Create remote directory if it doesn't exist
        try:
            ssh_conn.sftp.stat(remote_path)
        except:
            ssh_conn.sftp.mkdir(remote_path)
        
        if os.path.isdir(local_path):
            # Upload directory recursively
            for item in os.listdir(local_path):
                local_item = os.path.join(local_path, item)
                remote_item = os.path.join(remote_path, item)
                
                if os.path.isdir(local_item):
                    # Recursively upload subdirectory
                    upload_via_sftp(ssh_conn, local_item, remote_item)
                else:
                    # Upload file
                    ssh_conn.sftp.put(local_item, remote_item)
        else:
            # Upload single file
            ssh_conn.sftp.put(local_path, os.path.join(remote_path, os.path.basename(local_path)))
            
    except Exception as e:
        raise Exception(f"SFTP upload failed: {str(e)}")


def sync_directories(source, dest):
    """Sync directories (incremental copy)"""
    os.makedirs(dest, exist_ok=True)
    
    for root, dirs, files in os.walk(source):
        rel_path = os.path.relpath(root, source)
        dest_root = os.path.join(dest, rel_path) if rel_path != '.' else dest
        
        os.makedirs(dest_root, exist_ok=True)
        
        for file in files:
            source_file = os.path.join(root, file)
            dest_file = os.path.join(dest_root, file)
            
            # Only copy if newer or doesn't exist
            if not os.path.exists(dest_file) or os.path.getmtime(source_file) > os.path.getmtime(dest_file):
                shutil.copy2(source_file, dest_file)


def restore_worker(restore_id: str, restore_config: Dict, status_queue: Queue):
    """
    Worker function for restore operations
    Runs in separate process
    """
    start_time = time.time()
    
    try:
        logger.info(f"Restore worker started for {restore_id}")
        
        archive = restore_config['archive']
        dest_server_id = restore_config['dest_server_id']
        dest_path = restore_config['dest_path']
        data_dir = Path(restore_config['_data_dir'])
        
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 10,
            'message': 'Loading server configurations...'
        })
        
        # Load servers
        servers_file = data_dir / 'backup_servers.json'
        with open(servers_file, 'r') as f:
            all_servers = json.load(f)
        
        # Get source server (where backup is stored)
        source_server_id = archive.get('dest_server_id')  # backup destination = restore source
        source_server = next((s for s in all_servers if s['id'] == source_server_id), None)
        if not source_server:
            raise Exception(f"Backup storage server not found: {source_server_id}")
        
        # Get destination server (where to restore)
        dest_server = next((s for s in all_servers if s['id'] == dest_server_id), None)
        if not dest_server:
            raise Exception(f"Restore destination server not found: {dest_server_id}")
        
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 20,
            'message': f'Connecting to backup storage: {source_server["name"]}...'
        })
        
        # Connect to backup storage
        source_conn = create_connection(source_server['type'], **source_server)
        if not source_conn.connect():
            raise Exception(f"Failed to connect to backup storage: {source_server['name']}")
        
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 40,
            'message': f'Connecting to restore destination: {dest_server["name"]}...'
        })
        
        # Connect to restore destination
        dest_conn = create_connection(dest_server['type'], **dest_server)
        if not dest_conn.connect():
            source_conn.disconnect()
            raise Exception(f"Failed to connect to restore destination: {dest_server['name']}")
        
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 60,
            'message': 'Restoring files...'
        })
        
        # Perform restore
        backup_path = archive.get('destination_path')
        selective_items = restore_config.get('selective_items', [])
        
        # Download from backup storage to temp
        temp_dir = tempfile.mkdtemp(prefix='jarvis_restore_')
        
        if selective_items:
            # Selective restore - only download specified items
            status_queue.put({
                'restore_id': restore_id,
                'status': 'running',
                'progress': 60,
                'message': f'Restoring {len(selective_items)} selected items...'
            })
            
            for item_path in selective_items:
                item_relative = item_path.replace(backup_path, '').lstrip('/')
                source_item = os.path.join(backup_path, item_relative)
                dest_item = os.path.join(temp_dir, item_relative)
                
                if isinstance(source_conn, SSHConnection):
                    # Download specific item via SFTP
                    os.makedirs(os.path.dirname(dest_item), exist_ok=True)
                    download_via_sftp(source_conn, source_item, dest_item)
                else:
                    source_full = os.path.join(source_conn.mount_point, source_item.lstrip('/'))
                    if os.path.isdir(source_full):
                        shutil.copytree(source_full, dest_item, dirs_exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(dest_item), exist_ok=True)
                        shutil.copy2(source_full, dest_item)
        else:
            # Full restore - download entire backup
            status_queue.put({
                'restore_id': restore_id,
                'status': 'running',
                'progress': 60,
                'message': 'Restoring full backup...'
            })
            
            if isinstance(source_conn, SSHConnection):
                download_via_sftp(source_conn, backup_path, temp_dir)
            else:
                source_full = os.path.join(source_conn.mount_point, backup_path.lstrip('/'))
                shutil.copytree(source_full, temp_dir, dirs_exist_ok=True)
        
        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 80,
            'message': f'Uploading to {dest_path}...'
        })
        
        # Upload to destination
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
        
        # Cleanup
        shutil.rmtree(temp_dir)
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
        
    except Exception as e:
        import traceback
        logger.error(f"Restore worker failed: {e}")
        logger.error(traceback.format_exc())
        
        status_queue.put({
            'restore_id': restore_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Restore failed: {str(e)}',
            'failed_at': datetime.now().isoformat()
        })


class BackupManager:
    """Main backup manager - runs in Jarvis main process"""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.data_dir / 'backup_jobs.json'
        self.status_file = self.data_dir / 'backup_status.json'
        self.jobs = self._load_jobs()
        self.statuses = self._load_statuses()
        self.worker_processes = {}
        self.status_updater = None
        
    def _load_jobs(self):
        """Load backup jobs from disk"""
        if self.jobs_file.exists():
            with open(self.jobs_file, 'r') as f:
                return json.load(f)
        return {}
        
    def _save_jobs(self):
        """Save backup jobs to disk"""
        with open(self.jobs_file, 'w') as f:
            json.dump(self.jobs, f, indent=2)
            
    def _load_statuses(self):
        """Load backup statuses from disk"""
        if self.status_file.exists():
            with open(self.status_file, 'r') as f:
                return json.load(f)
        return {}
        
    def _save_statuses(self):
        """Save backup statuses to disk"""
        with open(self.status_file, 'w') as f:
            json.dump(self.statuses, f, indent=2)
            
    async def start(self):
        """Start the backup manager"""
        self.status_updater = asyncio.create_task(self._status_updater())
        logger.info("Backup manager started")
        
    async def stop(self):
        """Stop the backup manager"""
        if self.status_updater:
            self.status_updater.cancel()
            
        for process in self.worker_processes.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                
        logger.info("Backup manager stopped")
        
    async def _status_updater(self):
        """Background task to update job statuses from queue"""
        while True:
            try:
                while not status_queue.empty():
                    status_update = status_queue.get_nowait()
                    job_id = status_update['job_id']
                    
                    if job_id not in self.statuses:
                        self.statuses[job_id] = {}
                    self.statuses[job_id].update(status_update)
                    
                    self._save_statuses()
                    logger.info(f"Job {job_id}: {status_update.get('message', 'Status update')}")
                    
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
                
    def create_job(self, job_config: Dict) -> str:
        """Create a new backup job"""
        job_id = str(uuid.uuid4())
        job_config['id'] = job_id
        job_config['created_at'] = datetime.now().isoformat()
        
        self.jobs[job_id] = job_config
        self._save_jobs()
        
        logger.info(f"Created backup job {job_id}")
        return job_id
        
    def run_job(self, job_id: str) -> bool:
        """Run a backup job in separate process"""
        if job_id not in self.jobs:
            logger.error(f"Job {job_id} not found")
            return False
            
        if job_id in self.worker_processes and self.worker_processes[job_id].is_alive():
            logger.warning(f"Job {job_id} is already running")
            return False
            
        job_config = self.jobs[job_id].copy()
        # Add data_dir to job config so worker process can find servers
        job_config['_data_dir'] = str(self.data_dir)
        
        process = Process(
            target=backup_worker,
            args=(job_id, job_config, status_queue)
        )
        
        process.start()
        self.worker_processes[job_id] = process
        
        self.statuses[job_id] = {
            'job_id': job_id,
            'status': 'queued',
            'progress': 0,
            'message': 'Job queued',
            'started_at': datetime.now().isoformat()
        }
        self._save_statuses()
        
        logger.info(f"Started backup job {job_id} in process {process.pid}")
        return True
        
    def get_job_status(self, job_id: str) -> Dict:
        """Get status of a backup job"""
        return self.statuses.get(job_id, {})
        
    def get_all_jobs(self) -> Dict:
        """Get all backup jobs"""
        return self.jobs
        
    def delete_job(self, job_id: str) -> bool:
        """Delete a backup job"""
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
        """Get all configured servers"""
        servers_file = self.data_dir / 'backup_servers.json'
        if servers_file.exists():
            with open(servers_file, 'r') as f:
                return json.load(f)
        return []
    
    def add_server(self, server_config: Dict) -> str:
        """Add a new server configuration"""
        server_id = str(uuid.uuid4())
        server_config['id'] = server_id
        
        servers = self.get_all_servers()
        servers.append(server_config)
        
        servers_file = self.data_dir / 'backup_servers.json'
        with open(servers_file, 'w') as f:
            json.dump(servers, f, indent=2)
        
        logger.info(f"Added server {server_id}")
        return server_id
    
    def delete_server(self, server_id: str) -> bool:
        """Delete a server configuration"""
        servers = self.get_all_servers()
        filtered = [s for s in servers if s.get('id') != server_id]
        
        if len(filtered) < len(servers):
            servers_file = self.data_dir / 'backup_servers.json'
            with open(servers_file, 'w') as f:
                json.dump(filtered, f, indent=2)
            logger.info(f"Deleted server {server_id}")
            return True
        return False
    
    def get_all_archives(self) -> List[Dict]:
        """Get all backup archives"""
        archives_file = self.data_dir / 'backup_archives.json'
        if archives_file.exists():
            with open(archives_file, 'r') as f:
                return json.load(f)
        return []
    
    def delete_archive(self, archive_id: str) -> bool:
        """Delete a backup archive"""
        archives = self.get_all_archives()
        filtered = [a for a in archives if a.get('id') != archive_id]
        
        if len(filtered) < len(archives):
            archives_file = self.data_dir / 'backup_archives.json'
            with open(archives_file, 'w') as f:
                json.dump(filtered, f, indent=2)
            logger.info(f"Deleted archive {archive_id}")
            return True
        return False
    
    def start_restore(self, archive_id: str, dest_server_id: str, dest_path: str, overwrite: bool, selective_items: list = None) -> str:
        """Start a restore operation in separate process"""
        # Find archive
        archives = self.get_all_archives()
        archive = next((a for a in archives if a['id'] == archive_id), None)
        if not archive:
            raise Exception(f"Archive {archive_id} not found")
        
        # Create restore config
        restore_id = str(uuid.uuid4())
        restore_config = {
            'restore_id': restore_id,
            'archive': archive,
            'dest_server_id': dest_server_id,
            'dest_path': dest_path,
            'overwrite': overwrite,
            'selective_items': selective_items or [],
            '_data_dir': str(self.data_dir)
        }
        
        # Start restore worker
        process = Process(
            target=restore_worker,
            args=(restore_id, restore_config, status_queue)
        )
        process.start()
        self.worker_processes[restore_id] = process
        
        self.statuses[restore_id] = {
            'restore_id': restore_id,
            'status': 'queued',
            'progress': 0,
            'message': 'Restore queued',
            'started_at': datetime.now().isoformat()
        }
        self._save_statuses()
        
        logger.info(f"Started restore {restore_id} for archive {archive_id}")
        return restore_id


# API Routes
backup_manager = None

async def init_backup_module(app):
    """Initialize backup module"""
    global backup_manager
    data_dir = app.get('data_dir', '/data') + '/backup_module'
    backup_manager = BackupManager(data_dir)
    await backup_manager.start()
    logger.info("Backup module initialized")


async def cleanup_backup_module(app):
    """Cleanup backup module"""
    global backup_manager
    if backup_manager:
        await backup_manager.stop()


async def test_connection(request):
    """Test connection to remote system"""
    try:
        data = await request.json()
        
        conn = create_connection(
            data['type'],
            **data
        )
        
        if conn.connect():
            conn.disconnect()
            return web.json_response({
                'success': True,
                'message': 'Connection successful'
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Connection failed'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def browse_directory(request):
    """Browse remote directory"""
    try:
        data = await request.json()
        
        # Get server config from either 'server_config' or 'connection'
        server_config = data.get('server_config') or data.get('connection')
        if not server_config:
            return web.json_response({
                'success': False,
                'message': 'No server configuration provided'
            }, status=400)
        
        conn = create_connection(
            server_config['type'],
            **server_config
        )
        
        if not conn.connect():
            return web.json_response({
                'success': False,
                'message': 'Failed to connect to server. Check credentials.'
            }, status=400)
            
        path = data.get('path', '/')
        items = conn.list_directory(path)
        
        conn.disconnect()
        
        return web.json_response({
            'success': True,
            'files': items  # Frontend expects 'files' not 'items'
        })
        
    except Exception as e:
        logger.error(f"Directory browse failed: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def create_backup_job(request):
    """Create new backup job"""
    try:
        data = await request.json()
        job_id = backup_manager.create_job(data)
        
        return web.json_response({
            'success': True,
            'job_id': job_id
        })
        
    except Exception as e:
        logger.error(f"Job creation failed: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def run_backup_job(request):
    """Run backup job"""
    try:
        job_id = request.match_info['job_id']
        success = backup_manager.run_job(job_id)
        
        if success:
            return web.json_response({
                'success': True,
                'message': 'Job started'
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Failed to start job'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Job run failed: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def get_job_status(request):
    """Get job status"""
    try:
        job_id = request.match_info['job_id']
        status = backup_manager.get_job_status(job_id)
        
        return web.json_response({
            'success': True,
            'status': status
        })
        
    except Exception as e:
        logger.error(f"Get status failed: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def get_all_jobs(request):
    """Get all jobs"""
    try:
        jobs_dict = backup_manager.get_all_jobs()
        jobs_list = list(jobs_dict.values())
        
        return web.json_response({
            'jobs': jobs_list
        })
        
    except Exception as e:
        logger.error(f"Get jobs failed: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def delete_backup_job(request):
    """Delete backup job"""
    try:
        job_id = request.match_info['job_id']
        success = backup_manager.delete_job(job_id)
        
        if success:
            return web.json_response({
                'success': True,
                'message': 'Job deleted'
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Job not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Job deletion failed: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def get_servers(request):
    """Get all configured servers"""
    try:
        servers = backup_manager.get_all_servers()
        source_servers = [s for s in servers if s.get('server_type') == 'source']
        destination_servers = [s for s in servers if s.get('server_type') == 'destination']
        return web.json_response({
            'source_servers': source_servers,
            'destination_servers': destination_servers
        })
    except Exception as e:
        logger.error(f"Failed to get servers: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def add_server(request):
    """Add a new server configuration (ensures server_type persists)"""
    try:
        data = await request.json()

        # 🔧 Ensure server_type is present
        if not data.get("server_type"):
            conn_type = data.get("type", "")
            if conn_type == "ssh":
                data["server_type"] = "source"
            else:
                data["server_type"] = "destination"

        server_id = backup_manager.add_server(data)
        logger.info(f"Server added: {data.get('name')} ({data.get('server_type')})")

        return web.json_response({
            "success": True,
            "id": server_id,
            "message": "Server added successfully"
        })
    except Exception as e:
        logger.error(f"Failed to add server: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def delete_server(request):
    """Delete a server configuration"""
    try:
        server_id = request.match_info['server_id']
        success = backup_manager.delete_server(server_id)
        
        if success:
            return web.json_response({'success': True, 'message': 'Server deleted'})
        else:
            return web.json_response({'error': 'Server not found'}, status=404)
    except Exception as e:
        logger.error(f"Failed to delete server: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def get_archives(request):
    """Get all backup archives"""
    try:
        archives = backup_manager.get_all_archives()
        return web.json_response({'archives': archives})
    except Exception as e:
        logger.error(f"Failed to get archives: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def delete_archive(request):
    """Delete a backup archive"""
    try:
        archive_id = request.match_info['archive_id']
        success = backup_manager.delete_archive(archive_id)
        
        if success:
            return web.json_response({'success': True, 'message': 'Archive deleted'})
        else:
            return web.json_response({'error': 'Archive not found'}, status=404)
    except Exception as e:
        logger.error(f"Failed to delete archive: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def restore_backup(request):
    """Restore a backup to specified location"""
    try:
        data = await request.json()
        archive_id = data.get('archive_id')
        dest_server_id = data.get('destination_server_id')
        dest_path = data.get('destination_path')
        overwrite = data.get('overwrite', False)
        selective_items = data.get('selective_items', [])
        
        if not all([archive_id, dest_server_id, dest_path]):
            return web.json_response({
                'error': 'Missing required fields: archive_id, destination_server_id, destination_path'
            }, status=400)
        
        restore_id = backup_manager.start_restore(archive_id, dest_server_id, dest_path, overwrite, selective_items)
        
        return web.json_response({
            'success': True,
            'restore_id': restore_id,
            'message': 'Restore started'
        })
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return web.json_response({'error': str(e)}, status=500)


def setup_routes(app):
    """Setup API routes"""
    # Job routes
    app.router.add_post('/api/backup/jobs', create_backup_job)
    app.router.add_get('/api/backup/jobs', get_all_jobs)
    app.router.add_post('/api/backup/jobs/{job_id}/run', run_backup_job)
    app.router.add_get('/api/backup/jobs/{job_id}/status', get_job_status)
    app.router.add_delete('/api/backup/jobs/{job_id}', delete_backup_job)
    
    # Server routes
    app.router.add_get('/api/backup/servers', get_servers)
    app.router.add_post('/api/backup/servers', add_server)
    app.router.add_delete('/api/backup/servers/{server_id}', delete_server)
    
    # Archive routes
    app.router.add_get('/api/backup/archives', get_archives)
    app.router.add_delete('/api/backup/archives/{archive_id}', delete_archive)
    
    # Other routes
    app.router.add_post('/api/backup/test-connection', test_connection)
    app.router.add_post('/api/backup/browse', browse_directory)
    app.router.add_post('/api/backup/restore', restore_backup)
    
    app.on_startup.append(init_backup_module)
    app.on_cleanup.append(cleanup_backup_module)
