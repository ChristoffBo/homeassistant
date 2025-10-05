#!/usr/bin/env python3
# /app/backup.py
# Backup and Restore functionality for Jarvis Prime

import os
import tarfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from aiohttp import web
import logging

logger = logging.getLogger(__name__)


async def create_backup(request):
    """Create a tar.gz backup of all data"""
    try:
        # Paths to backup
        data_dir = Path("/data")
        share_dir = Path("/share/jarvis_prime")
        
        # Create temporary directory for staging backup
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_root = Path(tmpdir) / "jarvis_prime_backup"
            backup_root.mkdir()
            
            # Copy database
            db_path = data_dir / "jarvis.db"
            if db_path.exists():
                shutil.copy2(db_path, backup_root / "jarvis.db")
                logger.info(f"[backup] Added database: {db_path}")
            
            # Copy playbooks directory
            playbooks_dir = share_dir / "playbooks"
            if playbooks_dir.exists():
                shutil.copytree(playbooks_dir, backup_root / "playbooks")
                logger.info(f"[backup] Added playbooks directory")
            
            # Copy models directory (if exists)
            models_dir = share_dir / "models"
            if models_dir.exists():
                shutil.copytree(models_dir, backup_root / "models")
                logger.info(f"[backup] Added models directory")
            
            # Copy config file (if exists)
            config_file = share_dir / "config.yaml"
            if config_file.exists():
                shutil.copy2(config_file, backup_root / "config.yaml")
                logger.info(f"[backup] Added config file")
            
            # Create tar.gz archive
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            tar_path = Path(tmpdir) / f"jarvis_backup_{timestamp}.tar.gz"
            
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(backup_root, arcname="jarvis_prime_backup")
            
            logger.info(f"[backup] Created backup archive: {tar_path}")
            
            # Return the tar.gz file
            return web.FileResponse(
                path=str(tar_path),
                headers={
                    'Content-Type': 'application/gzip',
                    'Content-Disposition': f'attachment; filename="jarvis-prime-backup-{timestamp}.tar.gz"'
                }
            )
    
    except Exception as e:
        logger.error(f"[backup] Failed to create backup: {e}")
        return web.json_response(
            {"error": f"Backup creation failed: {str(e)}"},
            status=500
        )


async def restore_backup(request):
    """Restore from a tar.gz backup"""
    try:
        reader = await request.multipart()
        field = await reader.next()
        
        if not field or field.name != 'backup':
            return web.json_response(
                {"error": "No backup file provided"},
                status=400
            )
        
        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar.gz') as tmp_file:
            tmp_path = Path(tmp_file.name)
            
            # Write uploaded data
            size = 0
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                tmp_file.write(chunk)
                size += len(chunk)
            
            logger.info(f"[backup] Received backup file: {size} bytes")
        
        # Extract and restore
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_dir = Path(tmpdir)
            
            # Extract tar.gz
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(extract_dir)
            
            logger.info(f"[backup] Extracted backup to {extract_dir}")
            
            # Find the backup root directory
            backup_root = extract_dir / "jarvis_prime_backup"
            if not backup_root.exists():
                # Try to find it if structure is different
                subdirs = list(extract_dir.iterdir())
                if len(subdirs) == 1 and subdirs[0].is_dir():
                    backup_root = subdirs[0]
                else:
                    raise Exception("Invalid backup structure")
            
            # Restore database
            db_backup = backup_root / "jarvis.db"
            db_target = Path("/data/jarvis.db")
            if db_backup.exists():
                # Backup current database first
                if db_target.exists():
                    shutil.copy2(db_target, db_target.with_suffix('.db.bak'))
                shutil.copy2(db_backup, db_target)
                logger.info(f"[backup] Restored database")
            
            # Restore playbooks
            playbooks_backup = backup_root / "playbooks"
            playbooks_target = Path("/share/jarvis_prime/playbooks")
            if playbooks_backup.exists():
                if playbooks_target.exists():
                    shutil.rmtree(playbooks_target)
                shutil.copytree(playbooks_backup, playbooks_target)
                logger.info(f"[backup] Restored playbooks")
            
            # Restore models (if exists)
            models_backup = backup_root / "models"
            models_target = Path("/share/jarvis_prime/models")
            if models_backup.exists():
                if models_target.exists():
                    shutil.rmtree(models_target)
                shutil.copytree(models_backup, models_target)
                logger.info(f"[backup] Restored models")
            
            # Restore config (if exists)
            config_backup = backup_root / "config.yaml"
            config_target = Path("/share/jarvis_prime/config.yaml")
            if config_backup.exists():
                shutil.copy2(config_backup, config_target)
                logger.info(f"[backup] Restored config")
        
        # Clean up temp file
        tmp_path.unlink()
        
        logger.info(f"[backup] Restore completed successfully")
        return web.json_response({"success": True, "message": "Backup restored successfully"})
    
    except Exception as e:
        logger.error(f"[backup] Failed to restore backup: {e}")
        return web.json_response(
            {"error": f"Restore failed: {str(e)}"},
            status=500
        )


def register_routes(app):
    """Register backup/restore routes"""
    app.router.add_post("/api/backup/create", create_backup)
    app.router.add_post("/api/backup/restore", restore_backup)
