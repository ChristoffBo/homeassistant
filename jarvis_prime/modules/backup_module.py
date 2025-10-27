#!/usr/bin/env python3
\"\"\"
Jarvis Prime - Backup Module (Phase 2)
Agentless backup system with SSH/SMB/NFS support, archive extraction on restore, job scheduler loop
\"\"\"

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
                         error: str = None):
    \"\"\"
    Fan-out detailed backup job notification through Jarvis Prime's multi-channel system.
    \"\"\"
    try:
        import sys
        # Add parent directory to path to import bot
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from bot import process_incoming
        emoji = "✅" if status == "success" else "❌"
        title = f\"{emoji} Backup {job_name}\"
        message_parts = [
            f\"**Status:** {status.upper()}\",
            f\"**Job ID:** {job_id}\"
        ]
        if source_path:
            message_parts.append(f\"**Source:** {source_path}\")
        if dest_path:
            message_parts.append(f\"**Destination:** {dest_path}\")
        if size_mb is not None:
            message_parts.append(f\"**Size:** {size_mb:.2f} MB\")
        if duration is not None:
            message_parts.append(f\"**Duration:** {duration:.1f}s\")
        if error:
            message_parts.append(f\"**Error:** {error}\")
        message = \"\\n\".join(f\"• {part}\" for part in message_parts)
        priority = 3 if status == "success" else 8
        process_incoming(title, message, source="backup", priority=priority)
        logger.info(f\"Backup notification sent for job {job_id}\")
    except Exception as e:
        try:
            from errors import notify_error
            notify_error(f\"[Backup Fanout Failure] {str(e)}\", context="backup")
        except Exception:
            logger.error(f\"Backup fanout failed: {e}\")

class BackupConnection:
    \"\"\"Base class for backup connections\"\"\"
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
        raise NotImplementedError
    def disconnect(self):
        raise NotImplementedError
    def list_directory(self, path: str) -> List[Dict]:
        raise NotImplementedError

class SSHConnection(BackupConnection):
    \"\"\"SSH/SFTP connection handler\"\"\"
    def __init__(self, host: str, username: str, password: str, port: int = 22):
        super().__init__('ssh', host, username, password, port=port)
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
                timeout=10
            )
            self.sftp = self.client.open_sftp()
            self.connected = True
            logger.info(f\"SSH connected to {self.host}\")
            return True
        except Exception as e:
            logger.error(f\"SSH connection failed to {self.host}: {e}\")
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
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            return output, error
        except Exception as e:
            logger.error(f\"Command execution failed: {e}\")
            return \"\", str(e)

class SMBConnection(BackupConnection):
    \"\"\"SMB/CIFS connection handler\"\"\"
    def __init__(self, host: str, username: str, password: str, share: str, port: int = 445):
        super().__init__('smb', host, username, password, port=port, share=share)
        self.mount_point = None

    def connect(self):
        try:
            self.mount_point = tempfile.mkdtemp(prefix='jarvis_smb_')
            mount_cmd = [
                'mount', '-t', 'cifs',
                f'//{self.host}/{self.share}',
                self.mount_point,
                '-o', f'username={self.username},password={self.password},vers=3.0'
            ]
            result = subprocess.run(mount_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.connected = True
                logger.info(f\"SMB connected to //{self.host}/{self.share}\")
                return True
            else:
                logger.error(f\"SMB mount failed: {result.stderr}\")
                return False
        except Exception as e:
            logger.error(f\"SMB connection failed: {e}\")
            return False

    def disconnect(self):
        try:
            if self.mount_point and os.path.exists(self.mount_point):
                subprocess.run(['umount', self.mount_point], capture_output=True)
                os.rmdir(self.mount_point)
            self.connected = False
        except:
            pass

    def list_directory(self, path: str) -> List[Dict]:
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
    \"\"\"NFS connection handler\"\"\"
    def __init__(self, host: str, export_path: str, username: str = None, password: str = None):
        super().__init__('nfs', host, username or '', password or '', export_path=export_path)
        self.mount_point = None

    def connect(self):
        try:
            self.mount_point = tempfile.mkdtemp(prefix='jarvis_nfs_')
            mount_cmd = [
                'mount', '-t', 'nfs',
                f'{self.host}:{self.export_path}',
                self.mount_point
            ]
            result = subprocess.run(mount_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.connected = True
                logger.info(f\"NFS connected to {self.host}:{self.export_path}\")
                return True
            else:
                logger.error(f\"NFS mount failed: {result.stderr}\")
                return False
        except Exception as e:
            logger.error(f\"NFS connection failed: {e}\")
            return False

    def disconnect(self):
        try:
            if self.mount_point and os.path.exists(self.mount_point):
                subprocess.run(['umount', self.mount_point], capture_output=True)
                os.rmdir(self.mount_point)
            self.connected = False
        except:
            pass

    def list_directory(self, path: str) -> List[Dict]:
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
            logger.error(f\"Failed to list NFS directory {path}: {e}\")
            return []

def create_connection(conn_type: str, **kwargs) -> BackupConnection:
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
        raise ValueError(f\"Unknown connection type: {conn_type}\")

def ensure_rsync_installed(ssh_conn):
    try:
        stdout, stderr = ssh_conn.execute_command('which rsync')
        if stdout.strip():
            return True
        logger.info(f\"rsync not found on {ssh_conn.host}, attempting to install...\")
        install_cmd = 'sudo apt-get update && sudo apt-get install -y rsync || yum install -y rsync'
        stdout, stderr = ssh_conn.execute_command(install_cmd)
        stdout, stderr = ssh_conn.execute_command('which rsync')
        if stdout.strip():
            logger.info(f\"Successfully installed rsync on {ssh_conn.host}\")
            return True
        else:
            logger.warning(f\"Failed to auto-install rsync on {ssh_conn.host}: {stderr}\")
            return False
    except Exception as e:
        logger.error(f\"Error checking/installing rsync: {e}\")
        return False

def create_archive_record(job_id: str, job_config: Dict, duration: float, data_dir: Path, real_size_mb: float):
    archives_file = data_dir / 'backup_archives.json'
    if archives_file.exists():
        with open(archives_file, 'r') as f:
            archives = json.load(f)
    else:
        archives = []
    archive_id = str(uuid.uuid4())
    timestamp = datetime.now()
    archive_name_slug = job_config.get('name', f\"job_{job_id}\").replace(' ', '_').lower()
    archive_record = {
        'id': archive_id,
        'job_id': job_id,
        'job_name': job_config.get('name', 'Unknown Job'),
        'archive_name': f\"{archive_name_slug}_{timestamp.strftime('%Y%m%d_%H%M%S')}\",
        'source_paths': job_config.get('paths', []),
        'destination_path': job_config.get('destination_path'),
        'source_server_id': job_config.get('source_server_id'),
        'dest_server_id': job_config.get('destination_server_id'),
        'backup_type': job_config.get('backup_type', 'full'),
        'compressed': job_config.get('compress', True),
        'size_mb': real_size_mb,
        'created_at': timestamp.isoformat(),
        'duration': duration,
        'status': 'completed'
    }
    archives.append(archive_record)
    with open(archives_file, 'w') as f:
        json.dump(archives, f, indent=2)
    logger.info(f\"Created archive record {archive_id} for job {job_id}\")

def calculate_file_size_mb(file_path: str) -> float:
    try:
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)
    except Exception as e:
        logger.warning(f\"Failed to get size for {file_path}: {e}\")
        return 0.0

def perform_full_backup(source_conn, dest_conn, source_paths, dest_path, compress, status_queue, job_id):
    start_time = time.time()
    temp_dir = tempfile.mkdtemp(prefix='jarvis_backup_')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        for idx, source_path in enumerate(source_paths):
            progress = 30 + int((idx * 40) / len(source_paths))
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
        status_queue.put({
            'job_id': job_id,
            'status': 'running',
            'progress': 85,
            'message': 'Uploading to destination...'
        })
        if isinstance(dest_conn, SSHConnection):
            if is_archive:
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
        # calculate size
        real_size_mb = calculate_file_size_mb(upload_file) if is_archive else calculate_file_size_mb(temp_dir)
        duration = time.time() - start_time
        status_queue.put({
            'job_id': job_id,
            'status': 'completed',
            'progress': 100,
            'message': f'Backup completed in {duration:.1f}s',
            'completed_at': datetime.now().isoformat()
        })
        source_conn.disconnect()
        dest_conn.disconnect()
        create_archive_record(job_id, job_config, duration, Path(job_config.get('_data_dir')), real_size_mb)
        backup_fanout_notify(job_id=job_id, job_name=job_config.get('name', 'Unknown Job'), status='success',
                             source_path=", ".join(source_paths[:3]) + (f" +{len(source_paths)-3} more" if len(source_paths) > 3 else ""),
                             dest_path=job_config.get('destination_path'),
                             size_mb=real_size_mb,
                             duration=duration)
        return True
    except Exception as e:
        error_msg = str(e)
        logger.error(f\"Full backup failed: {error_msg}\\nTraceback: {traceback.format_exc()}\")
        status_queue.put({
            'job_id': job_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Backup failed: {error_msg}'
        })
        backup_fanout_notify(job_id=job_id, job_name=job_config.get('name', 'Unknown Job'), status='failed',
                             source_path=", ".join(source_paths[:3]),
                             dest_path=job_config.get('destination_path'),
                             error=error_msg)
        raise

def perform_incremental_backup(source_conn, dest_conn, source_paths, dest_path, compress, status_queue, job_id):
    try:
        for idx, source_path in enumerate(source_paths):
            progress = 30 + int((idx * 60) / len(source_paths))
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
            elif isinstance(source_conn, SSHConnection):
                temp_dir = tempfile.mkdtemp(prefix='jarvis_sync_')
                download_via_rsync(source_conn, source_path, temp_dir, incremental=True)
                dest_full_path = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'), os.path.basename(source_path))
                sync_directories(temp_dir, dest_full_path)
                shutil.rmtree(temp_dir)
            elif isinstance(dest_conn, SSHConnection):
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                temp_dir = tempfile.mkdtemp(prefix='jarvis_sync_')
                sync_directories(source_full_path, temp_dir)
                upload_via_rsync(dest_conn, temp_dir, os.path.join(dest_path, os.path.basename(source_path)))
                shutil.rmtree(temp_dir)
            else:
                source_full_path = os.path.join(source_conn.mount_point, source_path.lstrip('/'))
                dest_full_path = os.path.join(dest_conn.mount_point, dest_path.lstrip('/'), os.path.basename(source_path))
                sync_directories(source_full_path, dest_full_path)
        return True
    except Exception as e:
        error_msg = str(e)
        logger.error(f\"Incremental backup failed: {error_msg}\\nTraceback: {traceback.format_exc()}\")
        status_queue.put({
            'job_id': job_id,
            'status': 'failed',
            'progress': 0,
            'message': f'Backup failed: {error_msg}'
        })
        raise

def download_via_rsync(ssh_conn, remote_path, local_path, incremental=False):
    os.makedirs(local_path, exist_ok=True)
    try:
        subprocess.run(['which', 'rsync'], check=True, capture_output=True)
        subprocess.run(['which', 'sshpass'], check=True, capture_output=True)
        has_rsync = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_rsync = False
    if not has_rsync:
        logger.warning("rsync not available, using SFTP fallback (slower)")
        download_via_sftp(ssh_conn, remote_path, local_path)
        return
    rsync_cmd = [
        'rsync',
        '-avz',
        '--progress',
        '-e', f'sshpass -p \"{ssh_conn.password}\" ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}',
        f'{ssh_conn.username}@{ssh_conn.host}:{remote_path}/',
        local_path + '/'
    ]
    if incremental:
        rsync_cmd.insert(2, '--update')
    try:
        subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_output = e.stderr if e.stderr else e.stdout
        raise Exception(f\"rsync failed (exit code {e.returncode}): {error_output}\")

def download_via_sftp(ssh_conn, remote_path, local_path):
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
                    ssh_conn.sftp.get(remote_item, local_item)
        else:
            ssh_conn.sftp.get(remote_path, os.path.join(local_path, os.path.basename(remote_path)))
    except Exception as e:
        raise Exception(f\"SFTP download failed: {str(e)}\")

def upload_via_rsync(ssh_conn, local_path, remote_path):
    try:
        subprocess.run(['which', 'rsync'], check=True, capture_output=True)
        subprocess.run(['which', 'sshpass'], check=True, capture_output=True)
        has_rsync = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_rsync = False
    if not has_rsync:
        logger.warning(\"rsync not available, using SFTP fallback (slower)\")
        upload_via_sftp(ssh_conn, local_path, remote_path)
        return
    rsync_cmd = [
        'rsync',
        '-avz',
        '--progress',
        '-e', f'sshpass -p \"{ssh_conn.password}\" ssh -o StrictHostKeyChecking=no -p {ssh_conn.port}',
        local_path + ('/' if os.path.isdir(local_path) else ''),
        f'{ssh_conn.username}@{ssh_conn.host}:{remote_path}/'
    ]
    try:
        subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_output = e.stderr if e.stderr else e.stdout
        raise Exception(f\"rsync failed (exit code {e.returncode}): {error_output}\")

def upload_via_sftp(ssh_conn, local_path, remote_path):
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
                    ssh_conn.sftp.put(local_item, remote_item)
        else:
            ssh_conn.sftp.put(local_path, os.path.join(remote_path, os.path.basename(local_path)))
    except Exception as e:
        raise Exception(f\"SFTP upload failed: {str(e)}\")

def sync_directories(source, dest):
    os.makedirs(dest, exist_ok=True)
    for root, dirs, files in os.walk(source):
        rel = os.path.relpath(root, source)
        dest_root = os.path.join(dest, rel) if rel != '.' else dest
        os.makedirs(dest_root, exist_ok=True)
        for file in files:
            src = os.path.join(root, file)
            dst = os.path.join(dest_root, file)
            if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                shutil.copy2(src, dst)

def extract_archive(archive_file: str, extract_to: str):
    if archive_file.endswith('.tar.gz') or archive_file.endswith('.tar'):
        try:
            with tarfile.open(archive_file, 'r:*') as tar:
                tar.extractall(path=extract_to)
            return True
        except Exception as e:
            raise Exception(f\"Extraction failed: {e}\")
    else:
        # Not a compressed archive, treat as normal directory/transfer upload
        return False

def restore_worker(restore_id: str, restore_config: Dict, status_queue: Queue):
    start_time = time.time()
    try:
        logger.info(f\"Restore worker started for {restore_id}\")
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
        servers_file = data_dir / 'backup_servers.json'
        with open(servers_file, 'r') as f:
            all_servers = json.load(f)
        source_server = next((s for s in all_servers if s['id'] == archive.get('dest_server_id')), None)
        if not source_server:
            raise Exception(f\"Backup storage server not found: {archive.get('dest_server_id')}\")
        dest_server = next((s for s in all_servers if s['id'] == dest_server_id), None)
        if not dest_server:
            raise Exception(f\"Restore destination server not found: {dest_server_id}\")

        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 30,
            'message': f\"Connecting to backup storage: {source_server['name']}...\"
        })
        source_conn = create_connection(source_server['type'], **source_server)
        if not source_conn.connect():
            raise Exception(f\"Failed to connect to backup storage: {source_server['name']}\")

        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 50,
            'message': f\"Connecting to restore destination: {dest_server['name']}...\"
        })
        dest_conn = create_connection(dest_server['type'], **dest_server)
        if not dest_conn.connect():
            source_conn.disconnect()
            raise Exception(f\"Failed to connect to restore destination: {dest_server['name']}\")

        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 60,
            'message': 'Restoring files...'
        })
        backup_path = archive.get('destination_path')
        temp_dir = tempfile.mkdtemp(prefix='jarvis_restore_')
        # Download archive or directory
        if isinstance(source_conn, SSHConnection):
            remote_file = f\"{backup_path}/{archive.get('archive_name', '')}\" if archive.get('archive_name') else backup_path
            local_temp = os.path.join(temp_dir, os.path.basename(remote_file))
            source_conn.sftp.get(remote_file, local_temp)
            # Extract if archive file
            if extract_archive(local_temp, temp_dir):
                pass  # extracted, continue
            else:
                # Not archive? extract by copying
                download_via_sftp(source_conn, backup_path, temp_dir)
        else:
            source_full = os.path.join(source_conn.mount_point, backup_path.lstrip('/'))
            # Check if it's a tar/tar.gz
            if os.path.isfile(source_full) and (source_full.endswith('.tar.gz') or source_full.endswith('.tar')):
                shutil.copy2(source_full, temp_dir)
                if extract_archive(os.path.join(temp_dir, os.path.basename(source_full)), temp_dir):
                    pass
            else:
                shutil.copytree(source_full, temp_dir, dirs_exist_ok=True)

        status_queue.put({
            'restore_id': restore_id,
            'status': 'running',
            'progress': 75,
            'message': f'Uploading to {dest_path}...'
        })
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
        shutil.rmtree(temp_dir)
        source_conn.disconnect()
        dest_conn.disconnect()
        duration = time.time() - start_time
        status_queue.put({
            'restore_id': restore_id,
            'status': 'completed',
            'progress': 100,
            'message': f\"Restore completed in {duration:.1f}s\",
            'completed_at': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f\"Restore worker failed: {e}\\n{traceback.format_exc()}\")
        status_queue.put({
            'restore_id': restore_id,
            'status': 'failed',
            'progress': 0,
            'message': f\"Restore failed: {str(e)}\",
            'failed_at': datetime.now().isoformat()
        })

class BackupManager:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.data_dir / 'backup_jobs.json'
        self.status_file = self.data_dir / 'backup_status.json'
        self.jobs = self._load_jobs()
        self.statuses = self._load_statuses()
        self.worker_processes = {}
        self.status_updater = None
        self.scheduler_task = None

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
        self.scheduler_task = asyncio.create_task(self._job_scheduler())
        logger.info(\"Backup manager started with scheduler\")

    async def stop(self):
        if self.status_updater:
            self.status_updater.cancel()
        if self.scheduler_task:
            self.scheduler_task.cancel()
        for process in self.worker_processes.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        logger.info(\"Backup manager stopped\")

    async def _status_updater(self):
        while True:
            try:
                while not status_queue.empty():
                    status_update = status_queue.get_nowait()
                    job_id = status_update.get('job_id') or status_update.get('restore_id')
                    if job_id not in self.statuses:
                        self.statuses[job_id] = {}
                    self.statuses[job_id].update(status_update)
                    self._save_statuses()
                    logger.info(f\"Job {job_id}: {status_update.get('message', 'Status update')}\")
                finished = []
                for jid, process in self.worker_processes.items():
                    if not process.is_alive():
                        finished.append(jid)
                for jid in finished:
                    del self.worker_processes[jid]
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f\"Status updater error: {e}\")
                await asyncio.sleep(1)

    async def _job_scheduler(self):
        while True:
            try:
                now = datetime.now()
                for job_id, cfg in self.jobs.items():
                    interval_hours = cfg.get('interval_hours')
                    enabled = cfg.get('enabled', True)
                    last_run = self.statuses.get(job_id, {}).get('started_at')
                    if enabled and interval_hours and last_run:
                        last_dt = datetime.fromisoformat(last_run)
                        if now - last_dt >= timedelta(hours=interval_hours):
                            logger.info(f\"Auto-running scheduled job {job_id}\")
                            self.run_job(job_id)
                await asyncio.sleep(300)  # check every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f\"Scheduler loop error: {e}\")
                await asyncio.sleep(60)

    def create_job(self, job_config: Dict) -> str:
        job_id = str(uuid.uuid4())
        job_config['id'] = job_id
        job_config['created_at'] = datetime.now().isoformat()
        self.jobs[job_id] = job_config
        self._save_jobs()
        logger.info(f\"Created backup job {job_id}\")
        return job_id

    def run_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            logger.error(f\"Job {job_id} not found\")
            return False
        if job_id in self.worker_processes and self.worker_processes[job_id].is_alive():
            logger.warning(f\"Job {job_id} already running\")
            return False
        job_config = self.jobs[job_id].copy()
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
        logger.info(f\"Started backup job {job_id} in process {process.pid}\")
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
            logger.info(f\"Deleted backup job {job_id}\")
            return True
        return False

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
        servers_file = self.data_dir / 'backup_servers.json'
        with open(servers_file, 'w') as f:
            json.dump(servers, f, indent=2)
        logger.info(f\"Added server {server_id}\")
        return server_id

    def delete_server(self, server_id: str) -> bool:
        servers = self.get_all_servers()
        filtered = [s for s in servers if s.get('id') != server_id]
        if len(filtered) < len(servers):
            servers_file = self.data_dir / 'backup_servers.json'
            with open(servers_file, 'w') as f:
                json.dump(filtered, f, indent=2)
            logger.info(f\"Deleted server {server_id}\")
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
        filtered = [a for a in archives if a.get('id') != archive_id]
        if len(filtered) < len(archives):
            archives_file = self.data_dir / 'backup_archives.json'
            with open(archives_file, 'w') as f:
                json.dump(filtered, f, indent=2)
            logger.info(f\"Deleted archive {archive_id}\")
            return True
        return False

    def start_restore(self, archive_id: str, dest_server_id: str, dest_path: str, overwrite: bool, selective_items: list = None) -> str:
        archives = self.get_all_archives()
        archive = next((a for a in archives if a['id'] == archive_id), None)
        if not archive:
            raise Exception(f\"Archive {archive_id} not found\")
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
        logger.info(f\"Started restore {restore_id} for archive {archive_id}\")
        return restore_id

# API Routes
backup_manager = None

async def init_backup_module(app):
    global backup_manager
    data_dir = app.get('data_dir', '/data') + '/backup_module'
    backup_manager = BackupManager(data_dir)
    await backup_manager.start()
    logger.info(\"Backup module initialized (Phase2)\")

async def cleanup_backup_module(app):
    global backup_manager
    if backup_manager:
        await backup_manager.stop()

async def test_connection(request):
    try:
        data = await request.json()
        conn = create_connection(data['type'], **data)
        if conn.connect():
            conn.disconnect()
            return web.json_response({'success': True, 'message': 'Connection successful'})
        else:
            return web.json_response({'success': False, 'message': 'Connection failed'}, status=400)
    except Exception as e:
        logger.error(f\"Connection test failed: {e}\")
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def browse_directory(request):
    try:
        data = await request.json()
        server_config = data.get('server_config') or data.get('connection')
        if not server_config:
            return web.json_response({'success': False, 'message': 'No server configuration provided'}, status=400)
        conn = create_connection(server_config['type'], **server_config)
        if not conn.connect():
            return web.json_response({'success': False, 'message': 'Failed to connect to server. Check credentials.'}, status=400)
        path = data.get('path', '/')
        items = conn.list_directory(path)
        conn.disconnect()
        return web.json_response({'success': True, 'files': items})
    except Exception as e:
        logger.error(f\"Directory browse failed: {e}\")
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def create_backup_job(request):
    try:
        data = await request.json()
        job_id = backup_manager.create_job(data)
        return web.json_response({'success': True, 'job_id': job_id})
    except Exception as e:
        logger.error(f\"Job creation failed: {e}\")
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def run_backup_job(request):
    try:
        job_id = request.match_info['job_id']
        success = backup_manager.run_job(job_id)
        if success:
            return web.json_response({'success': True, 'message': 'Job started'})
        else:
            return web.json_response({'success': False, 'message': 'Failed to start job'}, status=400)
    except Exception as e:
        logger.error(f\"Job run failed: {e}\")
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def get_job_status(request):
    try:
        job_id = request.match_info['job_id']
        status = backup_manager.get_job_status(job_id)
        return web.json_response({'success': True, 'status': status})
    except Exception as e:
        logger.error(f\"Get status failed: {e}\")
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def get_all_jobs(request):
    try:
        jobs_dict = backup_manager.get_all_jobs()
        jobs_list = list(jobs_dict.values())
        return web.json_response({'jobs': jobs_list})
    except Exception as e:
        logger.error(f\"Get jobs failed: {e}\")
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def delete_backup_job(request):
    try:
        job_id = request.match_info['job_id']
        success = backup_manager.delete_job(job_id)
        if success:
            return web.json_response({'success': True, 'message': 'Job deleted'})
        else:
            return web.json_response({'success': False, 'message': 'Job not found'}, status=404)
    except Exception as e:
        logger.error(f\"Job deletion failed: {e}\")
        return web.json_response({'success': False, 'message': str(e)}, status=500)

async def get_servers(request):
    try:
        servers = backup_manager.get_all_servers()
        source_servers = [s for s in servers if s.get('server_type') == 'source']
        destination_servers = [s for s in servers if s.get('server_type') == 'destination']
        return web.json_response({'source_servers': source_servers, 'destination_servers': destination_servers})
    except Exception as e:
        logger.error(f\"Failed to get servers: {e}\")
        return web.json_response({'error': str(e)}, status=500)

async def add_server(request):
    try:
        data = await request.json()
        server_id = backup_manager.add_server(data)
        return web.json_response({'success': True, 'id': server_id, 'message': 'Server added successfully'})
    except Exception as e:
        logger.error(f\"Failed to add server: {e}\")
        return web.json_response({'error': str(e)}, status=500)

async def delete_server(request):
    try:
        server_id = request.match_info['server_id']
        success = backup_manager.delete_server(server_id)
        if success:
            return web.json_response({'success': True, 'message': 'Server deleted'})
        else:
            return web.json_response({'error': 'Server not found'}, status=404)
    except Exception as e:
        logger.error(f\"Failed to delete server: {e}\")
        return web.json_response({'error': str(e)}, status=500)

async def get_archives(request):
    try:
        archives = backup_manager.get_all_archives()
        return web.json_response({'archives': archives})
    except Exception as e:
        logger.error(f\"Failed to get archives: {e}\")
        return web.json_response({'error': str(e)}, status=500)

async def delete_archive(request):
    try:
        archive_id = request.match_info['archive_id']
        success = backup_manager.delete_archive(archive_id)
        if success:
            return web.json_response({'success': True, 'message': 'Archive deleted'})
        else:
            return web.json_response({'error': 'Archive not found'}, status=404)
    except Exception as e:
        logger.error(f\"Failed to delete archive: {e}\")
        return web.json_response({'error': str(e)}, status=500)

async def restore_backup(request):
    try:
        data = await request.json()
        archive_id = data.get('archive_id')
        dest_server_id = data.get('destination_server_id')
        dest_path = data.get('destination_path')
        overwrite = data.get('overwrite', False)
        selective_items = data.get('selective_items', [])
        if not all([archive_id, dest_server_id, dest_path]):
            return web.json_response({'error': 'Missing required fields: archive_id, destination_server_id, destination_path'}, status=400)
        restore_id = backup_manager.start_restore(archive_id, dest_server_id, dest_path, overwrite, selective_items)
        return web.json_response({'success': True, 'restore_id': restore_id, 'message': 'Restore started'})
    except Exception as e:
        logger.error(f\"Restore failed: {e}\")
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
    app.router.add_post('/api/backup/test-connection', test_connection)
    app.router.add_post('/api/backup/browse', browse_directory)
    app.router.add_post('/api/backup/restore', restore_backup)
    app.on_startup.append(init_backup_module)
    app.on_cleanup.append(cleanup_backup_module)