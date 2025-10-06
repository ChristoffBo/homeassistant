#!/usr/bin/env python3
# /app/backup.py
# Backup and Restore functionality for Jarvis Prime (fixed version for Home Assistant)

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
    """Create a tar.gz backup of all data (persistent-safe for Home Assistant)"""
    try:
        # Define base paths
        data_dir = Path("/data")
        share_dir = Path("/share/jarvis_prime")
        backup_dir = share_dir / "backups"

        # Ensure backup directory exists
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Create a unique backup folder under /tmp for staging
        tmpdir = Path(tempfile.mkdtemp(prefix="jarvis_backup_"))
        backup_root = tmpdir / "jarvis_prime_backup"
        backup_root.mkdir(parents=True, exist_ok=True)

        # --- Copy important data ---
        db_path = data_dir / "jarvis.db"
        if db_path.exists():
            shutil.copy2(db_path, backup_root / "jarvis.db")
            logger.info(f"[backup] Added database: {db_path}")
        else:
            logger.info(f"[backup] Skipped missing database: {db_path}")

        playbooks_dir = share_dir / "playbooks"
        if playbooks_dir.exists():
            shutil.copytree(playbooks_dir, backup_root / "playbooks", dirs_exist_ok=True)
            logger.info("[backup] Added playbooks directory")
        else:
            logger.info(f"[backup] Skipped missing directory: {playbooks_dir}")

        models_dir = share_dir / "models"
        if models_dir.exists():
            shutil.copytree(models_dir, backup_root / "models", dirs_exist_ok=True)
            logger.info("[backup] Added models directory")
        else:
            logger.info(f"[backup] Skipped missing directory: {models_dir}")

        config_file = share_dir / "config.yaml"
        if config_file.exists():
            shutil.copy2(config_file, backup_root / "config.yaml")
            logger.info("[backup] Added config file")
        else:
            logger.info(f"[backup] Skipped missing config file: {config_file}")

        # --- Create tar.gz archive ---
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tar_path = backup_dir / f"jarvis_backup_{timestamp}.tar.gz"

        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(backup_root, arcname="jarvis_prime_backup")

        # Set permissions for HA access
        os.chmod(tar_path, 0o644)
        logger.info(f"[backup] Created backup archive: {tar_path}")

        # Clean up temporary staging folder
        shutil.rmtree(tmpdir, ignore_errors=True)

        # Serve the file for download
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

        # Save uploaded file to /share/jarvis_prime/backups
        backup_dir = Path("/share/jarvis_prime/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, dir=backup_dir, suffix='.tar.gz') as tmp_file:
            tmp_path = Path(tmp_file.name)
            size = 0
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                tmp_file.write(chunk)
                size += len(chunk)

            logger.info(f"[backup] Received backup file: {tmp_path} ({size} bytes)")

        # --- Extract and restore ---
        with tempfile.TemporaryDirectory() as tmp_extract_dir:
            extract_dir = Path(tmp_extract_dir)
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(extract_dir)

            backup_root = extract_dir / "jarvis_prime_backup"
            if not backup_root.exists():
                subdirs = [p for p in extract_dir.iterdir() if p.is_dir()]
                if len(subdirs) == 1:
                    backup_root = subdirs[0]
                else:
                    raise Exception("Invalid backup structure")

            # Restore database
            db_backup = backup_root / "jarvis.db"
            db_target = Path("/data/jarvis.db")
            if db_backup.exists():
                if db_target.exists():
                    shutil.copy2(db_target, db_target.with_suffix('.db.bak'))
                shutil.copy2(db_backup, db_target)
                logger.info("[backup] Restored database")

            # Restore playbooks
            playbooks_backup = backup_root / "playbooks"
            playbooks_target = Path("/share/jarvis_prime/playbooks")
            if playbooks_backup.exists():
                if playbooks_target.exists():
                    shutil.rmtree(playbooks_target)
                shutil.copytree(playbooks_backup, playbooks_target, dirs_exist_ok=True)
                logger.info("[backup] Restored playbooks")

            # Restore models
            models_backup = backup_root / "models"
            models_target = Path("/share/jarvis_prime/models")
            if models_backup.exists():
                if models_target.exists():
                    shutil.rmtree(models_target)
                shutil.copytree(models_backup, models_target, dirs_exist_ok=True)
                logger.info("[backup] Restored models")

            # Restore config
            config_backup = backup_root / "config.yaml"
            config_target = Path("/share/jarvis_prime/config.yaml")
            if config_backup.exists():
                shutil.copy2(config_backup, config_target)
                logger.info("[backup] Restored config")

        # Delete uploaded backup
        tmp_path.unlink(missing_ok=True)
        logger.info("[backup] Restore completed successfully")

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
