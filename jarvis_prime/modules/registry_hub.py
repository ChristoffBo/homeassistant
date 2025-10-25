#!/usr/bin/env python3
"""
Jarvis Registry Hub - Docker Registry Proxy with Update Detection
Single-file implementation with embedded registry binary management
"""

import os
import sys
import json
import sqlite3
import subprocess
import threading
import time
import hashlib
import shutil
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
import requests
from flask import Blueprint, request, jsonify, Response
from aiohttp import web
import asyncio
import logging

# ============================================================================
# CONFIGURATION (Embedded)
# ============================================================================

DEFAULT_CONFIG = {
    "registry_binary_url": "https://github.com/distribution/distribution/releases/download/v2.8.3/registry_2.8.3_linux_amd64.tar.gz",
    "registry_binary_path": "/usr/local/bin/registry",
    "registry_port": 5001,
    "registry_host": "localhost",
    "storage_path": "/share/jarvis_prime/registry",
    "db_path": "/data/jarvis.db",
    "check_interval_hours": 12,
    "auto_pull": True,
    "keep_versions": 2,
    "max_storage_gb": 50,
    "purge_history_days": 30,
    "notifications_enabled": True,
    "storage_backend": {
        "type": "local",  # local, nfs, smb
        "local": {
            "path": "/share/jarvis_prime/registry"
        },
        "nfs": {
            "server": "",
            "export": "",
            "mount_point": "/mnt/registry-nfs",
            "options": "rw,sync,hard,intr"
        },
        "smb": {
            "server": "",
            "share": "",
            "username": "",
            "password": "",
            "mount_point": "/mnt/registry-smb",
            "options": "vers=3.0,dir_mode=0777,file_mode=0666"
        }
    },
    "supported_registries": {
        "docker.io": {
            "name": "Docker Hub",
            "url": "https://registry-1.docker.io",
            "enabled": True
        },
        "ghcr.io": {
            "name": "GitHub Container Registry",
            "url": "https://ghcr.io",
            "enabled": True
        },
        "lscr.io": {
            "name": "LinuxServer.io",
            "url": "https://lscr.io",
            "enabled": True
        },
        "quay.io": {
            "name": "Quay.io",
            "url": "https://quay.io",
            "enabled": True
        }
    }
}

REGISTRY_CONFIG_TEMPLATE = """version: 0.1
log:
  level: info
  fields:
    service: registry
storage:
  filesystem:
    rootdirectory: {storage_path}
  delete:
    enabled: true
http:
  addr: {host}:{port}
  headers:
    X-Content-Type-Options: [nosniff]
health:
  storagedriver:
    enabled: true
    interval: 10s
    threshold: 3
proxy:
  remoteurl: {upstream}
"""

# ============================================================================
# GLOBALS
# ============================================================================

_registry_process = None
_update_checker_thread = None
_notify_callback = None
_logger = logging.getLogger("registry_hub")
_db_conn = None

# ============================================================================
# DATABASE SETUP
# ============================================================================

def init_database(db_path: str):
    """Initialize SQLite database with registry tables"""
    global _db_conn
    
    _db_conn = sqlite3.connect(db_path, check_same_thread=False)
    _db_conn.row_factory = sqlite3.Row
    
    cursor = _db_conn.cursor()
    
    # Images table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registry_images (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tag TEXT NOT NULL,
            digest TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            pulled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            upstream_digest TEXT,
            update_available INTEGER DEFAULT 0,
            auto_pull INTEGER DEFAULT 1,
            keep_versions INTEGER DEFAULT 2,
            last_checked TIMESTAMP,
            UNIQUE(name, tag, digest)
        )
    """)
    
    # History table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registry_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT NOT NULL,
            action TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            details TEXT
        )
    """)
    
    # Settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registry_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    
    # Version history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registry_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT NOT NULL,
            tag TEXT NOT NULL,
            digest TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            pulled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_current INTEGER DEFAULT 0
        )
    """)
    
    _db_conn.commit()
    _logger.info("Database initialized")

def get_db():
    """Get database connection"""
    return _db_conn

# ============================================================================
# STORAGE BACKEND MANAGEMENT
# ============================================================================

def mount_nfs_storage(config: Dict[str, Any]) -> bool:
    """Mount NFS storage backend"""
    try:
        nfs_config = config["storage_backend"]["nfs"]
        server = nfs_config["server"]
        export = nfs_config["export"]
        mount_point = nfs_config["mount_point"]
        options = nfs_config.get("options", "rw,sync,hard,intr")
        
        if not server or not export:
            _logger.error("NFS server and export path required")
            return False
        
        # Create mount point
        os.makedirs(mount_point, exist_ok=True)
        
        # Check if already mounted
        result = subprocess.run(["mountpoint", "-q", mount_point], capture_output=True)
        if result.returncode == 0:
            _logger.info(f"NFS already mounted at {mount_point}")
            return True
        
        # Mount NFS
        mount_source = f"{server}:{export}"
        mount_cmd = ["mount", "-t", "nfs", "-o", options, mount_source, mount_point]
        
        _logger.info(f"Mounting NFS: {mount_source} to {mount_point}")
        result = subprocess.run(mount_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            _logger.error(f"Failed to mount NFS: {result.stderr}")
            return False
        
        _logger.info(f"NFS mounted successfully at {mount_point}")
        return True
        
    except Exception as e:
        _logger.error(f"Error mounting NFS: {e}")
        return False

def mount_smb_storage(config: Dict[str, Any]) -> bool:
    """Mount SMB/CIFS storage backend"""
    try:
        smb_config = config["storage_backend"]["smb"]
        server = smb_config["server"]
        share = smb_config["share"]
        username = smb_config.get("username", "")
        password = smb_config.get("password", "")
        mount_point = smb_config["mount_point"]
        options = smb_config.get("options", "vers=3.0,dir_mode=0777,file_mode=0666")
        
        if not server or not share:
            _logger.error("SMB server and share required")
            return False
        
        # Create mount point
        os.makedirs(mount_point, exist_ok=True)
        
        # Check if already mounted
        result = subprocess.run(["mountpoint", "-q", mount_point], capture_output=True)
        if result.returncode == 0:
            _logger.info(f"SMB already mounted at {mount_point}")
            return True
        
        # Build mount source
        mount_source = f"//{server}/{share}"
        
        # Build options with credentials
        mount_options = options
        if username:
            mount_options += f",username={username}"
        if password:
            mount_options += f",password={password}"
        else:
            mount_options += ",guest"
        
        mount_cmd = ["mount", "-t", "cifs", "-o", mount_options, mount_source, mount_point]
        
        _logger.info(f"Mounting SMB: {mount_source} to {mount_point}")
        result = subprocess.run(mount_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            _logger.error(f"Failed to mount SMB: {result.stderr}")
            return False
        
        _logger.info(f"SMB mounted successfully at {mount_point}")
        return True
        
    except Exception as e:
        _logger.error(f"Error mounting SMB: {e}")
        return False

def unmount_storage(mount_point: str) -> bool:
    """Unmount storage backend"""
    try:
        # Check if mounted
        result = subprocess.run(["mountpoint", "-q", mount_point], capture_output=True)
        if result.returncode != 0:
            _logger.info(f"Nothing mounted at {mount_point}")
            return True
        
        # Unmount
        _logger.info(f"Unmounting {mount_point}")
        result = subprocess.run(["umount", mount_point], capture_output=True, text=True)
        
        if result.returncode != 0:
            _logger.error(f"Failed to unmount: {result.stderr}")
            return False
        
        _logger.info(f"Unmounted {mount_point} successfully")
        return True
        
    except Exception as e:
        _logger.error(f"Error unmounting storage: {e}")
        return False

def setup_storage_backend(config: Dict[str, Any]) -> Optional[str]:
    """Setup storage backend and return storage path"""
    try:
        backend_type = config["storage_backend"]["type"]
        
        if backend_type == "local":
            storage_path = config["storage_backend"]["local"]["path"]
            os.makedirs(storage_path, exist_ok=True)
            _logger.info(f"Using local storage: {storage_path}")
            return storage_path
            
        elif backend_type == "nfs":
            if mount_nfs_storage(config):
                storage_path = config["storage_backend"]["nfs"]["mount_point"]
                os.makedirs(storage_path, exist_ok=True)
                _logger.info(f"Using NFS storage: {storage_path}")
                return storage_path
            else:
                _logger.error("Failed to mount NFS storage")
                return None
                
        elif backend_type == "smb":
            if mount_smb_storage(config):
                storage_path = config["storage_backend"]["smb"]["mount_point"]
                os.makedirs(storage_path, exist_ok=True)
                _logger.info(f"Using SMB storage: {storage_path}")
                return storage_path
            else:
                _logger.error("Failed to mount SMB storage")
                return None
        else:
            _logger.error(f"Unknown storage backend type: {backend_type}")
            return None
            
    except Exception as e:
        _logger.error(f"Error setting up storage backend: {e}")
        return None

def test_storage_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test storage backend connection"""
    try:
        backend_type = config["storage_backend"]["type"]
        
        if backend_type == "local":
            path = config["storage_backend"]["local"]["path"]
            
            # Test write access
            test_file = os.path.join(path, ".storage_test")
            os.makedirs(path, exist_ok=True)
            
            with open(test_file, 'w') as f:
                f.write("test")
            
            os.remove(test_file)
            
            # Get disk space
            stat = os.statvfs(path)
            total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            
            return {
                "success": True,
                "type": "local",
                "path": path,
                "total_gb": round(total_gb, 2),
                "free_gb": round(free_gb, 2)
            }
            
        elif backend_type == "nfs":
            nfs_config = config["storage_backend"]["nfs"]
            mount_point = nfs_config["mount_point"]
            
            # Check if mounted
            result = subprocess.run(["mountpoint", "-q", mount_point], capture_output=True)
            is_mounted = result.returncode == 0
            
            if is_mounted:
                stat = os.statvfs(mount_point)
                total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
                free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                
                return {
                    "success": True,
                    "type": "nfs",
                    "server": nfs_config["server"],
                    "export": nfs_config["export"],
                    "mounted": True,
                    "total_gb": round(total_gb, 2),
                    "free_gb": round(free_gb, 2)
                }
            else:
                # Try to mount
                if mount_nfs_storage(config):
                    return test_storage_connection(config)
                else:
                    return {
                        "success": False,
                        "type": "nfs",
                        "error": "Failed to mount NFS share"
                    }
                    
        elif backend_type == "smb":
            smb_config = config["storage_backend"]["smb"]
            mount_point = smb_config["mount_point"]
            
            # Check if mounted
            result = subprocess.run(["mountpoint", "-q", mount_point], capture_output=True)
            is_mounted = result.returncode == 0
            
            if is_mounted:
                stat = os.statvfs(mount_point)
                total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
                free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                
                return {
                    "success": True,
                    "type": "smb",
                    "server": smb_config["server"],
                    "share": smb_config["share"],
                    "mounted": True,
                    "total_gb": round(total_gb, 2),
                    "free_gb": round(free_gb, 2)
                }
            else:
                # Try to mount
                if mount_smb_storage(config):
                    return test_storage_connection(config)
                else:
                    return {
                        "success": False,
                        "type": "smb",
                        "error": "Failed to mount SMB share"
                    }
        else:
            return {
                "success": False,
                "error": f"Unknown storage backend type: {backend_type}"
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# ============================================================================
# REGISTRY BINARY MANAGEMENT
# ============================================================================

def download_registry_binary(url: str, dest: str) -> bool:
    """Download and extract registry binary if not present"""
    try:
        if os.path.exists(dest):
            _logger.info(f"Registry binary already exists at {dest}")
            return True
        
        _logger.info(f"Downloading registry binary from {url}")
        
        # Download to temp file
        temp_tar = "/tmp/registry.tar.gz"
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        with open(temp_tar, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        _logger.info("Extracting registry binary")
        
        # Extract
        with tarfile.open(temp_tar, 'r:gz') as tar:
            # Find the registry binary in the archive
            for member in tar.getmembers():
                if member.name.endswith('registry') or member.name == 'registry':
                    member.name = os.path.basename(member.name)
                    tar.extract(member, path=os.path.dirname(dest))
                    break
        
        # Make executable
        os.chmod(dest, 0o755)
        
        # Cleanup
        os.remove(temp_tar)
        
        _logger.info(f"Registry binary installed to {dest}")
        return True
        
    except Exception as e:
        _logger.error(f"Failed to download registry binary: {e}")
        return False

def create_registry_config(config: Dict[str, Any], storage_path: str) -> str:
    """Create registry configuration file - Docker Hub as primary upstream"""
    config_path = "/tmp/registry_config.yml"
    
    # Use Docker Hub as the primary pull-through cache
    # Other registries are pulled directly via Docker CLI
    upstream_url = config["supported_registries"]["docker.io"]["url"]
    
    content = REGISTRY_CONFIG_TEMPLATE.format(
        storage_path=storage_path,
        host=config["registry_host"],
        port=config["registry_port"],
        upstream=upstream_url
    )
    
    with open(config_path, 'w') as f:
        f.write(content)
    
    return config_path

def start_registry_process(binary_path: str, config_path: str) -> Optional[subprocess.Popen]:
    """Start registry binary as subprocess"""
    global _registry_process
    
    try:
        _logger.info(f"Starting registry process: {binary_path}")
        
        _registry_process = subprocess.Popen(
            [binary_path, "serve", config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait a moment and check if it started
        time.sleep(2)
        
        if _registry_process.poll() is not None:
            stdout, stderr = _registry_process.communicate()
            _logger.error(f"Registry process failed to start: {stderr}")
            return None
        
        _logger.info(f"Registry process started (PID: {_registry_process.pid})")
        return _registry_process
        
    except Exception as e:
        _logger.error(f"Failed to start registry process: {e}")
        return None

def stop_registry_process():
    """Stop registry subprocess"""
    global _registry_process
    
    if _registry_process:
        _logger.info("Stopping registry process")
        _registry_process.terminate()
        try:
            _registry_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _registry_process.kill()
        _registry_process = None

# ============================================================================
# REGISTRY API INTERACTION
# ============================================================================

def get_registry_url(config: Dict[str, Any]) -> str:
    """Get local registry URL"""
    return f"http://{config['registry_host']}:{config['registry_port']}"

def registry_api_call(endpoint: str, method: str = "GET", config: Dict = None, **kwargs) -> Optional[requests.Response]:
    """Make API call to local registry"""
    if config is None:
        config = load_config()
    
    url = f"{get_registry_url(config)}{endpoint}"
    
    try:
        response = requests.request(method, url, timeout=30, **kwargs)
        return response
    except Exception as e:
        _logger.error(f"Registry API call failed: {e}")
        return None

def list_cached_images(config: Dict) -> List[Dict[str, Any]]:
    """List all cached images from registry"""
    response = registry_api_call("/v2/_catalog", config=config)
    
    if not response or response.status_code != 200:
        return []
    
    catalog = response.json()
    repositories = catalog.get("repositories", [])
    
    images = []
    for repo in repositories:
        # Get tags
        tags_response = registry_api_call(f"/v2/{repo}/tags/list", config=config)
        if tags_response and tags_response.status_code == 200:
            tags_data = tags_response.json()
            tags = tags_data.get("tags", [])
            
            for tag in tags:
                # Get manifest to get digest and size
                manifest_response = registry_api_call(
                    f"/v2/{repo}/manifests/{tag}",
                    config=config,
                    headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
                )
                
                if manifest_response and manifest_response.status_code == 200:
                    digest = manifest_response.headers.get("Docker-Content-Digest", "")
                    manifest = manifest_response.json()
                    
                    # Calculate size
                    size = manifest.get("config", {}).get("size", 0)
                    for layer in manifest.get("layers", []):
                        size += layer.get("size", 0)
                    
                    images.append({
                        "name": repo,
                        "tag": tag,
                        "digest": digest,
                        "size": size
                    })
    
    return images

def detect_registry_from_image(image_name: str) -> tuple[str, str]:
    """
    Detect which registry an image comes from
    Returns: (registry_name, cleaned_image_name)
    """
    # GitHub Container Registry
    if image_name.startswith("ghcr.io/"):
        return "ghcr.io", image_name.replace("ghcr.io/", "")
    
    # LinuxServer.io images (lscr.io or linuxserver/ prefix)
    if image_name.startswith("lscr.io/"):
        return "lscr.io", image_name.replace("lscr.io/", "")
    if image_name.startswith("linuxserver/"):
        return "lscr.io", image_name
    
    # Quay.io
    if image_name.startswith("quay.io/"):
        return "quay.io", image_name.replace("quay.io/", "")
    
    # Docker Hub (default)
    return "docker.io", image_name

def pull_image_to_cache(image_name: str, tag: str, config: Dict) -> bool:
    """Pull image with smart multi-registry routing"""
    try:
        # Detect which registry this image is from
        registry, clean_name = detect_registry_from_image(image_name)
        
        _logger.info(f"Pulling {clean_name}:{tag} from {registry}")
        
        # Build full image reference with registry
        if registry == "docker.io":
            # Docker Hub - can use our proxy or direct
            full_image = f"{clean_name}:{tag}"
        elif registry == "ghcr.io":
            full_image = f"ghcr.io/{clean_name}:{tag}"
        elif registry == "lscr.io":
            full_image = f"lscr.io/{clean_name}:{tag}"
        elif registry == "quay.io":
            full_image = f"quay.io/{clean_name}:{tag}"
        else:
            full_image = f"{image_name}:{tag}"
        
        # Pull directly using docker CLI
        result = subprocess.run(
            ["docker", "pull", full_image],
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode == 0:
            _logger.info(f"Successfully pulled {image_name}:{tag} from {registry}")
            
            # Tag it locally for our cache tracking
            # This ensures we can track it in our local registry
            cache_tag = f"localhost:{config['registry_port']}/{clean_name}:{tag}"
            subprocess.run(
                ["docker", "tag", full_image, cache_tag],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return True
        else:
            _logger.error(f"Failed to pull {image_name}:{tag}: {result.stderr}")
            return False
            
    except Exception as e:
        _logger.error(f"Error pulling image: {e}")
        return False

def delete_image_from_cache(image_name: str, digest: str, config: Dict) -> bool:
    """Delete image from registry cache"""
    try:
        response = registry_api_call(
            f"/v2/{image_name}/manifests/{digest}",
            method="DELETE",
            config=config
        )
        
        if response and response.status_code in [200, 202]:
            _logger.info(f"Deleted {image_name}@{digest}")
            return True
        else:
            _logger.error(f"Failed to delete {image_name}@{digest}")
            return False
            
    except Exception as e:
        _logger.error(f"Error deleting image: {e}")
        return False

# ============================================================================
# UPDATE DETECTION
# ============================================================================

def get_upstream_digest(image_name: str, tag: str, registry: str = None) -> Optional[str]:
    """Get digest from upstream registry with auto-detection"""
    try:
        # Auto-detect registry if not specified
        if registry is None:
            registry, image_name = detect_registry_from_image(image_name)
        
        if registry == "docker.io":
            # Docker Hub
            if "/" not in image_name:
                image_name = f"library/{image_name}"
            
            # Get token
            token_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{image_name}:pull"
            token_response = requests.get(token_url, timeout=10)
            
            if token_response.status_code != 200:
                return None
            
            token = token_response.json().get("token")
            
            # Get manifest
            manifest_url = f"https://registry-1.docker.io/v2/{image_name}/manifests/{tag}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.docker.distribution.manifest.v2+json"
            }
            
            manifest_response = requests.get(manifest_url, headers=headers, timeout=10)
            
            if manifest_response.status_code == 200:
                return manifest_response.headers.get("Docker-Content-Digest")
        
        elif registry == "ghcr.io":
            # GitHub Container Registry
            manifest_url = f"https://ghcr.io/v2/{image_name}/manifests/{tag}"
            headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
            
            manifest_response = requests.get(manifest_url, headers=headers, timeout=10)
            
            if manifest_response.status_code == 200:
                return manifest_response.headers.get("Docker-Content-Digest")
        
        elif registry == "lscr.io":
            # LinuxServer.io Registry
            # Handle linuxserver/ prefix
            if image_name.startswith("linuxserver/"):
                image_name = image_name.replace("linuxserver/", "linuxserver/")
            
            manifest_url = f"https://lscr.io/v2/{image_name}/manifests/{tag}"
            headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
            
            manifest_response = requests.get(manifest_url, headers=headers, timeout=10)
            
            if manifest_response.status_code == 200:
                return manifest_response.headers.get("Docker-Content-Digest")
        
        elif registry == "quay.io":
            # Quay.io Registry
            manifest_url = f"https://quay.io/v2/{image_name}/manifests/{tag}"
            headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
            
            manifest_response = requests.get(manifest_url, headers=headers, timeout=10)
            
            if manifest_response.status_code == 200:
                return manifest_response.headers.get("Docker-Content-Digest")
        
        return None
        
    except Exception as e:
        _logger.error(f"Error getting upstream digest: {e}")
        return None

def check_for_updates():
    """Background thread to check for image updates"""
    config = load_config()
    
    while True:
        try:
            _logger.info("Checking for image updates")
            
            db = get_db()
            cursor = db.cursor()
            
            # Get all images that need checking
            cursor.execute("""
                SELECT id, name, tag, digest, upstream_digest, last_checked, auto_pull
                FROM registry_images
                WHERE auto_pull = 1
                  AND (last_checked IS NULL OR last_checked < datetime('now', '-' || ? || ' hours'))
            """, (config["check_interval_hours"],))
            
            images = cursor.fetchall()
            
            for image in images:
                image_name = image["name"]
                tag = image["tag"]
                local_digest = image["digest"]
                
                # Auto-detect registry and get clean name
                registry, clean_name = detect_registry_from_image(image_name)
                
                # Get upstream digest
                upstream_digest = get_upstream_digest(clean_name, tag, registry)
                
                if upstream_digest and upstream_digest != local_digest:
                    _logger.info(f"Update available for {image_name}:{tag}")
                    
                    # Mark as update available
                    cursor.execute("""
                        UPDATE registry_images
                        SET update_available = 1,
                            upstream_digest = ?,
                            last_checked = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (upstream_digest, image["id"]))
                    
                    # Send notification
                    send_notification(
                        "Registry Update Available",
                        f"New version of {image_name}:{tag} is available",
                        priority="normal"
                    )
                    
                    # Auto-pull if enabled
                    if config["auto_pull"] and image["auto_pull"]:
                        _logger.info(f"Auto-pulling {image_name}:{tag}")
                        if pull_image_to_cache(image_name, tag, config):
                            # Update database
                            cursor.execute("""
                                UPDATE registry_images
                                SET digest = ?,
                                    update_available = 0,
                                    pulled_at = CURRENT_TIMESTAMP
                                WHERE id = ?
                            """, (upstream_digest, image["id"]))
                            
                            # Add to version history
                            cursor.execute("""
                                INSERT INTO registry_versions (image_name, tag, digest, is_current)
                                VALUES (?, ?, ?, 1)
                            """, (image_name, tag, upstream_digest))
                            
                            # Mark old versions as not current
                            cursor.execute("""
                                UPDATE registry_versions
                                SET is_current = 0
                                WHERE image_name = ? AND tag = ? AND digest != ?
                            """, (image_name, tag, upstream_digest))
                            
                            # Clean old versions
                            cleanup_old_versions(image_name, tag, image.get("keep_versions", config["keep_versions"]))
                            
                            send_notification(
                                "Registry Auto-Update",
                                f"Successfully updated {image_name}:{tag}",
                                priority="normal"
                            )
                else:
                    # No update, just mark as checked
                    cursor.execute("""
                        UPDATE registry_images
                        SET last_checked = CURRENT_TIMESTAMP,
                            upstream_digest = ?
                        WHERE id = ?
                    """, (upstream_digest, image["id"]))
            
            db.commit()
            
        except Exception as e:
            _logger.error(f"Error in update checker: {e}")
        
        # Sleep until next check
        time.sleep(config["check_interval_hours"] * 3600)

def cleanup_old_versions(image_name: str, tag: str, keep_count: int):
    """Remove old versions beyond keep_count"""
    db = get_db()
    cursor = db.cursor()
    
    # Get all versions sorted by date
    cursor.execute("""
        SELECT id, digest FROM registry_versions
        WHERE image_name = ? AND tag = ?
        ORDER BY pulled_at DESC
    """, (image_name, tag))
    
    versions = cursor.fetchall()
    
    # Delete versions beyond keep_count
    if len(versions) > keep_count:
        for version in versions[keep_count:]:
            # Delete from cache
            config = load_config()
            delete_image_from_cache(image_name, version["digest"], config)
            
            # Delete from version history
            cursor.execute("DELETE FROM registry_versions WHERE id = ?", (version["id"],))
    
    db.commit()

# ============================================================================
# CONFIGURATION MANAGEMENT
# ============================================================================

def load_config() -> Dict[str, Any]:
    """Load configuration from database or use defaults"""
    db = get_db()
    cursor = db.cursor()
    
    config = DEFAULT_CONFIG.copy()
    
    cursor.execute("SELECT key, value FROM registry_settings")
    settings = cursor.fetchall()
    
    for setting in settings:
        key = setting["key"]
        value = setting["value"]
        
        # Parse value
        try:
            if value.lower() in ["true", "false"]:
                value = value.lower() == "true"
            elif value.isdigit():
                value = int(value)
            elif key in ["supported_registries", "upstream_registries"]:
                value = json.loads(value)
        except:
            pass
        
        config[key] = value
    
    return config

def save_config(config: Dict[str, Any]):
    """Save configuration to database"""
    db = get_db()
    cursor = db.cursor()
    
    for key, value in config.items():
        if key in ["supported_registries", "upstream_registries"]:
            value = json.dumps(value)
        elif isinstance(value, bool):
            value = str(value).lower()
        else:
            value = str(value)
        
        cursor.execute("""
            INSERT OR REPLACE INTO registry_settings (key, value)
            VALUES (?, ?)
        """, (key, value))
    
    db.commit()

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def sync_database_with_cache(config: Dict):
    """Sync database with actual cached images"""
    cached_images = list_cached_images(config)
    
    db = get_db()
    cursor = db.cursor()
    
    for image in cached_images:
        image_id = f"{image['name']}:{image['tag']}"
        
        cursor.execute("""
            INSERT OR REPLACE INTO registry_images (id, name, tag, digest, size, pulled_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (image_id, image["name"], image["tag"], image["digest"], image["size"]))
    
    db.commit()
    _logger.info(f"Synced {len(cached_images)} images to database")

def purge_old_history(days: int):
    """Purge history older than specified days"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        DELETE FROM registry_history
        WHERE timestamp < datetime('now', '-' || ? || ' days')
    """, (days,))
    
    deleted = cursor.rowcount
    db.commit()
    
    _logger.info(f"Purged {deleted} old history records")
    return deleted

def clean_orphaned_records():
    """Remove database records for images not in cache"""
    config = load_config()
    cached_images = list_cached_images(config)
    cached_ids = {f"{img['name']}:{img['tag']}" for img in cached_images}
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT id FROM registry_images")
    all_ids = {row["id"] for row in cursor.fetchall()}
    
    orphaned = all_ids - cached_ids
    
    for image_id in orphaned:
        cursor.execute("DELETE FROM registry_images WHERE id = ?", (image_id,))
    
    db.commit()
    _logger.info(f"Cleaned {len(orphaned)} orphaned records")
    return len(orphaned)

def reset_registry_database():
    """Nuclear reset - wipe all registry data from DB"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("DELETE FROM registry_images")
    cursor.execute("DELETE FROM registry_history")
    cursor.execute("DELETE FROM registry_settings")
    cursor.execute("DELETE FROM registry_versions")
    
    db.commit()
    _logger.info("Registry database reset complete")

def get_database_stats() -> Dict[str, Any]:
    """Get database statistics"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM registry_images")
    image_count = cursor.fetchone()["count"]
    
    cursor.execute("SELECT COUNT(*) as count FROM registry_history")
    history_count = cursor.fetchone()["count"]
    
    cursor.execute("""
        SELECT COUNT(*) as count FROM registry_history
        WHERE timestamp < datetime('now', '-30 days')
    """)
    purgeable_count = cursor.fetchone()["count"]
    
    # Get DB file size
    db_size = os.path.getsize(DEFAULT_CONFIG["db_path"]) if os.path.exists(DEFAULT_CONFIG["db_path"]) else 0
    
    return {
        "db_size": db_size,
        "image_count": image_count,
        "history_count": history_count,
        "purgeable_count": purgeable_count
    }

# ============================================================================
# STORAGE MANAGEMENT
# ============================================================================

def get_storage_stats(config: Dict) -> Dict[str, Any]:
    """Get storage usage statistics"""
    storage_path = config["storage_path"]
    
    if not os.path.exists(storage_path):
        return {"used": 0, "total": 0, "percent": 0}
    
    # Calculate directory size
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(storage_path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.exists(filepath):
                total_size += os.path.getsize(filepath)
    
    max_size = config["max_storage_gb"] * 1024 * 1024 * 1024
    percent = (total_size / max_size * 100) if max_size > 0 else 0
    
    return {
        "used": total_size,
        "total": max_size,
        "percent": round(percent, 2)
    }

def cleanup_storage(config: Dict):
    """Clean up old/unused image layers"""
    # Run registry garbage collection
    try:
        result = subprocess.run(
            [config["registry_binary_path"], "garbage-collect", "/tmp/registry_config.yml"],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            _logger.info("Storage cleanup completed")
            return True
        else:
            _logger.error(f"Storage cleanup failed: {result.stderr}")
            return False
    except Exception as e:
        _logger.error(f"Error during storage cleanup: {e}")
        return False

# ============================================================================
# NOTIFICATIONS
# ============================================================================

def send_notification(title: str, message: str, priority: str = "normal"):
    """Send notification via fanout system"""
    if _notify_callback and DEFAULT_CONFIG.get("notifications_enabled", True):
        try:
            _notify_callback({
                "source": "registry",
                "title": title,
                "message": message,
                "priority": priority
            })
        except Exception as e:
            _logger.error(f"Failed to send notification: {e}")

# ============================================================================
# FLASK BLUEPRINT (API)
# ============================================================================

registry_bp = Blueprint('registry', __name__)

@registry_bp.route('/images', methods=['GET'])
def api_list_images():
    """List all cached images"""
    try:
        config = load_config()
        
        # Get from database
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("""
            SELECT id, name, tag, digest, size, pulled_at, 
                   update_available, upstream_digest, last_checked
            FROM registry_images
            ORDER BY pulled_at DESC
        """)
        
        images = []
        for row in cursor.fetchall():
            # Detect registry for display
            registry, clean_name = detect_registry_from_image(row["name"])
            
            images.append({
                "id": row["id"],
                "name": row["name"],
                "tag": row["tag"],
                "digest": row["digest"],
                "size": row["size"],
                "pulled_at": row["pulled_at"],
                "update_available": bool(row["update_available"]),
                "last_checked": row["last_checked"],
                "registry": registry  # Show which registry this came from
            })
        
        return jsonify({"images": images})
        
    except Exception as e:
        _logger.error(f"Error listing images: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/images/pull', methods=['POST'])
def api_pull_image():
    """Manually pull an image"""
    try:
        data = request.get_json()
        image_name = data.get("image")
        
        if not image_name:
            return jsonify({"error": "image name required"}), 400
        
        # Parse image:tag
        if ":" in image_name:
            name, tag = image_name.rsplit(":", 1)
        else:
            name, tag = image_name, "latest"
        
        config = load_config()
        
        if pull_image_to_cache(name, tag, config):
            # Sync database
            sync_database_with_cache(config)
            
            # Log history
            db = get_db()
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO registry_history (image_name, action, details)
                VALUES (?, 'pull', 'Manual pull via UI')
            """, (f"{name}:{tag}",))
            db.commit()
            
            return jsonify({"success": True, "message": f"Pulled {name}:{tag}"})
        else:
            return jsonify({"error": "Pull failed"}), 500
            
    except Exception as e:
        _logger.error(f"Error pulling image: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/images/<image_id>', methods=['DELETE'])
def api_delete_image(image_id):
    """Delete an image from cache"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Get image details
        cursor.execute("SELECT name, tag, digest FROM registry_images WHERE id = ?", (image_id,))
        image = cursor.fetchone()
        
        if not image:
            return jsonify({"error": "Image not found"}), 404
        
        config = load_config()
        
        if delete_image_from_cache(image["name"], image["digest"], config):
            # Remove from database
            cursor.execute("DELETE FROM registry_images WHERE id = ?", (image_id,))
            
            # Log history
            cursor.execute("""
                INSERT INTO registry_history (image_name, action, details)
                VALUES (?, 'delete', 'Deleted via UI')
            """, (image_id,))
            
            db.commit()
            
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Delete failed"}), 500
            
    except Exception as e:
        _logger.error(f"Error deleting image: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/settings', methods=['GET'])
def api_get_settings():
    """Get registry settings"""
    try:
        config = load_config()
        
        # Filter to user-facing settings
        user_config = {
            "auto_pull": config.get("auto_pull", True),
            "check_interval_hours": config.get("check_interval_hours", 12),
            "keep_versions": config.get("keep_versions", 2),
            "max_storage_gb": config.get("max_storage_gb", 50),
            "purge_history_days": config.get("purge_history_days", 30),
            "notifications_enabled": config.get("notifications_enabled", True),
            "storage_backend": config.get("storage_backend", DEFAULT_CONFIG["storage_backend"])
        }
        
        return jsonify(user_config)
        
    except Exception as e:
        _logger.error(f"Error getting settings: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/settings', methods=['PUT'])
def api_save_settings():
    """Save registry settings"""
    try:
        data = request.get_json()
        
        config = load_config()
        config.update(data)
        save_config(config)
        
        return jsonify({"success": True})
        
    except Exception as e:
        _logger.error(f"Error saving settings: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/storage/test', methods=['POST'])
def api_test_storage():
    """Test storage backend connection"""
    try:
        data = request.get_json()
        
        # Create temporary config with test settings
        test_config = load_config().copy()
        test_config["storage_backend"] = data.get("storage_backend", test_config["storage_backend"])
        
        result = test_storage_connection(test_config)
        
        return jsonify(result)
        
    except Exception as e:
        _logger.error(f"Error testing storage: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@registry_bp.route('/stats', methods=['GET'])
def api_get_stats():
    """Get registry statistics"""
    try:
        config = load_config()
        
        storage_stats = get_storage_stats(config)
        db_stats = get_database_stats()
        
        # Get update count
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM registry_images WHERE update_available = 1")
        update_count = cursor.fetchone()["count"]
        
        return jsonify({
            "storage": storage_stats,
            "database": db_stats,
            "updates_available": update_count
        })
        
    except Exception as e:
        _logger.error(f"Error getting stats: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/db/purge-history', methods=['POST'])
def api_purge_history():
    """Purge old history records"""
    try:
        data = request.get_json() or {}
        days = data.get("days", 30)
        
        deleted = purge_old_history(days)
        
        return jsonify({"success": True, "deleted": deleted})
        
    except Exception as e:
        _logger.error(f"Error purging history: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/db/clean-orphaned', methods=['POST'])
def api_clean_orphaned():
    """Clean orphaned database records"""
    try:
        deleted = clean_orphaned_records()
        
        return jsonify({"success": True, "deleted": deleted})
        
    except Exception as e:
        _logger.error(f"Error cleaning orphaned records: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/db/reset', methods=['POST'])
def api_reset_database():
    """Reset registry database (requires confirmation)"""
    try:
        data = request.get_json()
        confirmation = data.get("confirmation", "")
        
        if confirmation != "RESET":
            return jsonify({"error": "Confirmation required"}), 400
        
        reset_registry_database()
        
        # Re-sync with cache
        config = load_config()
        sync_database_with_cache(config)
        
        return jsonify({"success": True})
        
    except Exception as e:
        _logger.error(f"Error resetting database: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/storage/cleanup', methods=['POST'])
def api_cleanup_storage():
    """Run storage garbage collection"""
    try:
        config = load_config()
        
        if cleanup_storage(config):
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Cleanup failed"}), 500
            
    except Exception as e:
        _logger.error(f"Error cleaning storage: {e}")
        return jsonify({"error": str(e)}), 500

@registry_bp.route('/check-updates', methods=['POST'])
def api_check_updates():
    """Manually trigger update check"""
    try:
        # This will be picked up by the background thread
        # For immediate check, we can trigger it directly
        
        config = load_config()
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("""
            SELECT id, name, tag, digest
            FROM registry_images
        """)
        
        images = cursor.fetchall()
        updates_found = 0
        
        for image in images:
            image_name = image["name"]
            tag = image["tag"]
            local_digest = image["digest"]
            
            # Auto-detect registry
            registry, clean_name = detect_registry_from_image(image_name)
            
            upstream_digest = get_upstream_digest(clean_name, tag, registry)
            
            if upstream_digest and upstream_digest != local_digest:
                updates_found += 1
                cursor.execute("""
                    UPDATE registry_images
                    SET update_available = 1,
                        upstream_digest = ?,
                        last_checked = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (upstream_digest, image["id"]))
        
        db.commit()
        
        return jsonify({"success": True, "updates_found": updates_found})
        
    except Exception as e:
        _logger.error(f"Error checking updates: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# INITIALIZATION
# ============================================================================

def init_registry(notify_callback: Optional[Callable] = None, db_path: str = None):
    """Initialize Registry Hub"""
    global _notify_callback, _update_checker_thread
    
    _notify_callback = notify_callback
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [registry_hub] %(levelname)s: %(message)s'
    )
    
    _logger.info("Initializing Registry Hub")
    
    # Initialize database
    if db_path:
        DEFAULT_CONFIG["db_path"] = db_path
    
    init_database(DEFAULT_CONFIG["db_path"])
    
    # Load config
    config = load_config()
    
    # Setup storage backend
    storage_path = setup_storage_backend(config)
    if not storage_path:
        _logger.error("Failed to setup storage backend")
        return False
    
    # Download registry binary if needed
    if not download_registry_binary(
        config["registry_binary_url"],
        config["registry_binary_path"]
    ):
        _logger.error("Failed to setup registry binary")
        return False
    
    # Create registry config with actual storage path
    config_path = create_registry_config(config, storage_path)
    
    # Start registry process
    if not start_registry_process(config["registry_binary_path"], config_path):
        _logger.error("Failed to start registry process")
        return False
    
    # Sync database with existing cache
    time.sleep(2)  # Give registry time to start
    sync_database_with_cache(config)
    
    # Start update checker thread
    _update_checker_thread = threading.Thread(target=check_for_updates, daemon=True)
    _update_checker_thread.start()
    
    _logger.info("Registry Hub initialized successfully")
    
    return True

def shutdown_registry():
    """Shutdown Registry Hub"""
    _logger.info("Shutting down Registry Hub")
    
    stop_registry_process()
    
    # Unmount remote storage if configured
    try:
        config = load_config()
        backend_type = config.get("storage_backend", {}).get("type", "local")
        
        if backend_type == "nfs":
            mount_point = config["storage_backend"]["nfs"]["mount_point"]
            unmount_storage(mount_point)
        elif backend_type == "smb":
            mount_point = config["storage_backend"]["smb"]["mount_point"]
            unmount_storage(mount_point)
    except Exception as e:
        _logger.warning(f"Error during storage unmount: {e}")
    
    if _db_conn:
        _db_conn.close()

# ============================================================================
# AIOHTTP COMPATIBILITY LAYER (runs all operations in threads)
# ============================================================================

async def init_registry_async(app, notification_callback, db_path):
    """Async wrapper for init_registry that also registers routes"""
    # Run init_registry in a thread so it doesn't block the event loop
    success = await asyncio.to_thread(
        init_registry,
        notify_callback=notification_callback,
        db_path=db_path
    )
    if success:
        # Register routes after successful init
        register_routes(app)
    return success

def register_routes(app):
    """Register aiohttp routes (all operations run in threads)"""
    
    # Images endpoints
    async def get_images_handler(request):
        try:
            # Run in thread to avoid blocking event loop
            images = await asyncio.to_thread(list_cached_images)
            return web.json_response({"images": images})
        except Exception as e:
            _logger.error(f"Error in get_images: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def pull_image_handler(request):
        try:
            data = await request.json()
            image_name = data.get("image")
            registry = data.get("registry", "docker.io")
            # Run pull in thread - it can take a while and does network I/O
            result = await asyncio.to_thread(manual_pull_image, image_name, registry)
            return web.json_response(result)
        except Exception as e:
            _logger.error(f"Error in pull_image: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def delete_image_handler(request):
        try:
            image_id = request.match_info.get('image_id')
            # Run delete in thread
            result = await asyncio.to_thread(delete_image, image_id)
            return web.json_response({"success": result})
        except Exception as e:
            _logger.error(f"Error in delete_image: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def check_updates_handler(request):
        try:
            # Run update check in thread - can take time with network requests
            result = await asyncio.to_thread(check_for_updates_manual)
            return web.json_response({"success": True, "updates": result})
        except Exception as e:
            _logger.error(f"Error in check_updates: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    # Stats endpoint
    async def get_stats_handler(request):
        try:
            # Run in thread
            stats = await asyncio.to_thread(get_registry_stats)
            return web.json_response(stats)
        except Exception as e:
            _logger.error(f"Error in get_stats: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    # Settings endpoints
    async def get_settings_handler(request):
        try:
            # Run in thread
            config = await asyncio.to_thread(load_config)
            return web.json_response(config)
        except Exception as e:
            _logger.error(f"Error in get_settings: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def put_settings_handler(request):
        try:
            data = await request.json()
            # Run in thread
            result = await asyncio.to_thread(save_config, data)
            return web.json_response({"success": True})
        except Exception as e:
            _logger.error(f"Error in put_settings: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    # Storage test endpoint
    async def test_storage_handler(request):
        try:
            data = await request.json()
            # Run in thread - may do I/O
            result = await asyncio.to_thread(test_storage_connection, data)
            return web.json_response(result)
        except Exception as e:
            _logger.error(f"Error in test_storage: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    # Database purge endpoint
    async def purge_history_handler(request):
        try:
            data = await request.json()
            days = data.get("days", 30)
            # Run in thread
            result = await asyncio.to_thread(purge_old_history, days)
            return web.json_response({"success": True, "deleted": result})
        except Exception as e:
            _logger.error(f"Error in purge_history: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    # Register all routes with aiohttp
    app.router.add_get('/api/registry/images', get_images_handler)
    app.router.add_post('/api/registry/pull', pull_image_handler)
    app.router.add_delete('/api/registry/images/{image_id}', delete_image_handler)
    app.router.add_post('/api/registry/check-updates', check_updates_handler)
    app.router.add_get('/api/registry/stats', get_stats_handler)
    app.router.add_get('/api/registry/settings', get_settings_handler)
    app.router.add_post('/api/registry/settings', put_settings_handler)
    app.router.add_post('/api/registry/storage/test', test_storage_handler)
    app.router.add_post('/api/registry/purge', purge_history_handler)
    
    _logger.info("[registry] aiohttp routes registered (all operations run in threads)")

# ============================================================================
# MAIN (for testing)
# ============================================================================

if __name__ == "__main__":
    def test_notify(data):
        print(f"NOTIFICATION: {data}")
    
    init_registry(notify_callback=test_notify)
    
    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_registry()
