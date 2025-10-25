#!/usr/bin/env python3
# /app/backup.py
# Comprehensive Backup and Restore functionality for Jarvis Prime
# Backs up: Database, Playbooks, Models, Config, Sentinel Templates, ALL settings

import os
import tarfile
import tempfile
import shutil
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from aiohttp import web
import logging
import traceback

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection"""
    db_path = Path("/data/jarvis.db")
    if not db_path.exists():
        logger.warning(f"[backup] Database not found at {db_path}")
        return None
    return sqlite3.connect(str(db_path))


def export_database_tables(backup_root):
    """Export all database tables as JSON for inspection and portability"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        db_export_dir = backup_root / "db_export"
        db_export_dir.mkdir(parents=True, exist_ok=True)
        
        cursor = conn.cursor()
        
        # Get all table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        logger.info(f"[backup] Exporting {len(tables)} database tables")
        
        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                # Get column names
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [col[1] for col in cursor.fetchall()]
                
                # Convert to list of dicts
                data = []
                for row in rows:
                    data.append(dict(zip(columns, row)))
                
                # Save as JSON
                table_file = db_export_dir / f"{table}.json"
                with open(table_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                
                logger.info(f"[backup] Exported table '{table}': {len(rows)} rows")
                
            except Exception as e:
                logger.warning(f"[backup] Failed to export table '{table}': {e}")
        
        # Create metadata file
        metadata = {
            "exported_at": datetime.now().isoformat(),
            "tables": tables,
            "total_tables": len(tables)
        }
        
        with open(db_export_dir / "_metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"[backup] Database export completed: {len(tables)} tables")
        
    except Exception as e:
        logger.error(f"[backup] Database export failed: {e}")
    finally:
        conn.close()


def backup_sentinel_data(backup_root):
    """Backup all Sentinel monitoring data"""
    sentinel_dir = backup_root / "sentinel"
    sentinel_dir.mkdir(parents=True, exist_ok=True)
    
    # Backup templates directory
    templates_source = Path("/share/jarvis_prime/sentinel_templates")
    if templates_source.exists():
        templates_dest = sentinel_dir / "templates"
        shutil.copytree(templates_source, templates_dest, dirs_exist_ok=True)
        logger.info(f"[backup] Backed up Sentinel templates: {len(list(templates_dest.glob('*.json')))} files")
    else:
        logger.info("[backup] No Sentinel templates directory found")
    
    # Export Sentinel database tables
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Sentinel servers
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sentinel_%'")
            sentinel_tables = [row[0] for row in cursor.fetchall()]
            
            for table in sentinel_tables:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [col[1] for col in cursor.fetchall()]
                
                data = [dict(zip(columns, row)) for row in rows]
                
                with open(sentinel_dir / f"{table}.json", 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                
                logger.info(f"[backup] Exported Sentinel table '{table}': {len(rows)} rows")
            
        except Exception as e:
            logger.error(f"[backup] Failed to backup Sentinel data: {e}")
        finally:
            conn.close()


def backup_analytics_data(backup_root):
    """Backup all Analytics monitoring data"""
    analytics_dir = backup_root / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        
        # Analytics services
        cursor.execute("SELECT * FROM analytics_services")
        services = cursor.fetchall()
        cursor.execute("PRAGMA table_info(analytics_services)")
        service_cols = [col[1] for col in cursor.fetchall()]
        services_data = [dict(zip(service_cols, row)) for row in services]
        
        with open(analytics_dir / "services.json", 'w') as f:
            json.dump(services_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(services_data)} analytics services")
        
        # Network devices
        cursor.execute("SELECT * FROM network_devices")
        devices = cursor.fetchall()
        cursor.execute("PRAGMA table_info(network_devices)")
        device_cols = [col[1] for col in cursor.fetchall()]
        devices_data = [dict(zip(device_cols, row)) for row in devices]
        
        with open(analytics_dir / "network_devices.json", 'w') as f:
            json.dump(devices_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(devices_data)} network devices")
        
        # Internet speed test settings
        cursor.execute("SELECT * FROM internet_speed_settings")
        speed_settings = cursor.fetchall()
        if speed_settings:
            cursor.execute("PRAGMA table_info(internet_speed_settings)")
            speed_cols = [col[1] for col in cursor.fetchall()]
            speed_data = [dict(zip(speed_cols, row)) for row in speed_settings]
            
            with open(analytics_dir / "speed_test_settings.json", 'w') as f:
                json.dump(speed_data, f, indent=2, default=str)
            logger.info(f"[backup] Backed up internet speed test settings")
        
        # Recent speed tests (last 100)
        cursor.execute("SELECT * FROM internet_speed_tests ORDER BY timestamp DESC LIMIT 100")
        speed_tests = cursor.fetchall()
        cursor.execute("PRAGMA table_info(internet_speed_tests)")
        test_cols = [col[1] for col in cursor.fetchall()]
        tests_data = [dict(zip(test_cols, row)) for row in speed_tests]
        
        with open(analytics_dir / "recent_speed_tests.json", 'w') as f:
            json.dump(tests_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(tests_data)} recent speed tests")
        
        # Analytics incidents
        cursor.execute("SELECT * FROM analytics_incidents")
        incidents = cursor.fetchall()
        cursor.execute("PRAGMA table_info(analytics_incidents)")
        incident_cols = [col[1] for col in cursor.fetchall()]
        incidents_data = [dict(zip(incident_cols, row)) for row in incidents]
        
        with open(analytics_dir / "incidents.json", 'w') as f:
            json.dump(incidents_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(incidents_data)} analytics incidents")
        
    except Exception as e:
        logger.error(f"[backup] Failed to backup analytics data: {e}")
    finally:
        conn.close()


def backup_orchestrator_data(backup_root):
    """Backup all Orchestrator data"""
    orch_dir = backup_root / "orchestrator"
    orch_dir.mkdir(parents=True, exist_ok=True)
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        
        # Servers
        cursor.execute("SELECT * FROM orch_servers")
        servers = cursor.fetchall()
        cursor.execute("PRAGMA table_info(orch_servers)")
        server_cols = [col[1] for col in cursor.fetchall()]
        servers_data = [dict(zip(server_cols, row)) for row in servers]
        
        with open(orch_dir / "servers.json", 'w') as f:
            json.dump(servers_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(servers_data)} orchestrator servers")
        
        # Schedules
        cursor.execute("SELECT * FROM orch_schedules")
        schedules = cursor.fetchall()
        cursor.execute("PRAGMA table_info(orch_schedules)")
        schedule_cols = [col[1] for col in cursor.fetchall()]
        schedules_data = [dict(zip(schedule_cols, row)) for row in schedules]
        
        with open(orch_dir / "schedules.json", 'w') as f:
            json.dump(schedules_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(schedules_data)} orchestrator schedules")
        
        # Job history (last 500)
        cursor.execute("SELECT * FROM orch_history ORDER BY started_at DESC LIMIT 500")
        history = cursor.fetchall()
        cursor.execute("PRAGMA table_info(orch_history)")
        history_cols = [col[1] for col in cursor.fetchall()]
        history_data = [dict(zip(history_cols, row)) for row in history]
        
        with open(orch_dir / "recent_history.json", 'w') as f:
            json.dump(history_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(history_data)} recent orchestrator jobs")
        
        # Backup options.json (orchestrator runtime options)
        options_file = Path("/data/options.json")
        if options_file.exists():
            shutil.copy2(options_file, orch_dir / "options.json")
            logger.info(f"[backup] Backed up options.json")
        else:
            logger.info(f"[backup] No options.json found")
        
    except Exception as e:
        logger.error(f"[backup] Failed to backup orchestrator data: {e}")
    finally:
        conn.close()


def backup_messages_data(backup_root):
    """Backup inbox messages (last 1000)"""
    messages_dir = backup_root / "messages"
    messages_dir.mkdir(parents=True, exist_ok=True)
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        
        # Recent messages
        cursor.execute("SELECT * FROM messages ORDER BY received_at DESC LIMIT 1000")
        messages = cursor.fetchall()
        cursor.execute("PRAGMA table_info(messages)")
        msg_cols = [col[1] for col in cursor.fetchall()]
        messages_data = [dict(zip(msg_cols, row)) for row in messages]
        
        with open(messages_dir / "recent_messages.json", 'w') as f:
            json.dump(messages_data, f, indent=2, default=str)
        logger.info(f"[backup] Backed up {len(messages_data)} recent messages")
        
    except Exception as e:
        logger.error(f"[backup] Failed to backup messages: {e}")
    finally:
        conn.close()


def create_backup_manifest(backup_root):
    """Create manifest file with backup metadata"""
    manifest = {
        "created_at": datetime.now().isoformat(),
        "jarvis_version": "5.0",
        "backup_contents": {
            "database": os.path.exists(backup_root / "jarvis.db"),
            "config": os.path.exists(backup_root / "config.yaml"),
            "options": os.path.exists(backup_root / "orchestrator/options.json"),
            "playbooks": os.path.exists(backup_root / "playbooks"),
            "models": os.path.exists(backup_root / "models"),
            "sentinel_templates": os.path.exists(backup_root / "sentinel/templates"),
            "analytics_services": os.path.exists(backup_root / "analytics/services.json"),
            "network_devices": os.path.exists(backup_root / "analytics/network_devices.json"),
            "speed_test_settings": os.path.exists(backup_root / "analytics/speed_test_settings.json"),
            "orchestrator_servers": os.path.exists(backup_root / "orchestrator/servers.json"),
            "orchestrator_schedules": os.path.exists(backup_root / "orchestrator/schedules.json"),
            "messages": os.path.exists(backup_root / "messages/recent_messages.json")
        }
    }
    
    with open(backup_root / "MANIFEST.json", 'w') as f:
        json.dump(manifest, f, indent=2)
    
    logger.info("[backup] Created backup manifest")
    return manifest


async def create_backup(request):
    """Create a comprehensive tar.gz backup of all Jarvis Prime data"""
    tmpdir = None
    try:
        logger.info("[backup] Starting comprehensive backup creation")
        
        # Paths
        data_dir = Path("/data")
        share_dir = Path("/share/jarvis_prime")

        # Create temporary directory for staging backup
        tmpdir = tempfile.TemporaryDirectory()
        backup_root = Path(tmpdir.name) / "jarvis_prime_backup"
        backup_root.mkdir(parents=True, exist_ok=True)

        # 1. Copy database (binary backup)
        db_path = data_dir / "jarvis.db"
        if db_path.exists():
            shutil.copy2(db_path, backup_root / "jarvis.db")
            logger.info(f"[backup] ✓ Database binary: {db_path.stat().st_size} bytes")
        else:
            logger.warning(f"[backup] ✗ Database not found: {db_path}")

        # 2. Export all database tables as JSON
        export_database_tables(backup_root)

        # 3. Backup Sentinel data
        backup_sentinel_data(backup_root)

        # 4. Backup Analytics data
        backup_analytics_data(backup_root)

        # 5. Backup Orchestrator data
        backup_orchestrator_data(backup_root)

        # 6. Backup Messages
        backup_messages_data(backup_root)

        # 7. Copy playbooks directory
        playbooks_dir = share_dir / "playbooks"
        if playbooks_dir.exists():
            shutil.copytree(playbooks_dir, backup_root / "playbooks", dirs_exist_ok=True)
            playbook_count = len(list((backup_root / "playbooks").glob("*")))
            logger.info(f"[backup] ✓ Playbooks: {playbook_count} files")
        else:
            logger.info(f"[backup] ✗ Playbooks directory not found")

        # 8. Copy models directory (if exists)
        models_dir = share_dir / "models"
        if models_dir.exists():
            shutil.copytree(models_dir, backup_root / "models", dirs_exist_ok=True)
            model_count = len(list((backup_root / "models").glob("*")))
            logger.info(f"[backup] ✓ Models: {model_count} files")
        else:
            logger.info(f"[backup] ✗ Models directory not found")

        # 9. Copy config file (if exists)
        config_file = share_dir / "config.yaml"
        if config_file.exists():
            shutil.copy2(config_file, backup_root / "config.yaml")
            logger.info(f"[backup] ✓ Config file")
        else:
            logger.info(f"[backup] ✗ Config file not found")

        # 10. Create manifest
        manifest = create_backup_manifest(backup_root)

        # Create permanent backups directory
        permanent_path = Path("/share/jarvis_prime/backups")
        permanent_path.mkdir(parents=True, exist_ok=True)

        # Create tar.gz archive
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tar_path = permanent_path / f"jarvis_backup_{timestamp}.tar.gz"

        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(backup_root, arcname="jarvis_prime_backup")

        backup_size = tar_path.stat().st_size
        logger.info(f"[backup] ✓ Created backup archive: {tar_path} ({backup_size:,} bytes)")
        
        # Log summary
        logger.info(f"[backup] === BACKUP COMPLETE ===")
        logger.info(f"[backup] Contents: {json.dumps(manifest['backup_contents'], indent=2)}")

        # Return the tar.gz file for download
        return web.FileResponse(
            path=str(tar_path),
            headers={
                "Content-Type": "application/gzip",
                "Content-Disposition": f'attachment; filename="jarvis-prime-backup-{timestamp}.tar.gz"'
            }
        )

    except Exception as e:
        logger.error(f"[backup] ✗ FAILED to create backup: {e}")
        logger.error(f"[backup] Traceback:\n{traceback.format_exc()}")
        return web.json_response(
            {"error": f"Backup creation failed: {str(e)}"},
            status=500
        )
    finally:
        if tmpdir and isinstance(tmpdir, tempfile.TemporaryDirectory):
            tmpdir.cleanup()


def restore_database_tables(backup_root):
    """Restore database tables from JSON exports"""
    db_export_dir = backup_root / "db_export"
    if not db_export_dir.exists():
        logger.info("[restore] No db_export directory found, skipping JSON restore")
        return
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        
        # Read metadata
        metadata_file = db_export_dir / "_metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)
            logger.info(f"[restore] Restoring {metadata['total_tables']} tables from JSON")
        
        # Restore each table
        for json_file in db_export_dir.glob("*.json"):
            if json_file.name == "_metadata.json":
                continue
            
            table_name = json_file.stem
            
            try:
                with open(json_file) as f:
                    data = json.load(f)
                
                if not data:
                    continue
                
                # Get columns from first row
                columns = list(data[0].keys())
                placeholders = ','.join(['?' for _ in columns])
                
                # Clear existing data
                cursor.execute(f"DELETE FROM {table_name}")
                
                # Insert data
                for row in data:
                    values = [row.get(col) for col in columns]
                    cursor.execute(
                        f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})",
                        values
                    )
                
                conn.commit()
                logger.info(f"[restore] ✓ Restored table '{table_name}': {len(data)} rows")
                
            except Exception as e:
                logger.warning(f"[restore] Failed to restore table '{table_name}': {e}")
        
    except Exception as e:
        logger.error(f"[restore] Database table restore failed: {e}")
    finally:
        conn.close()


def restore_sentinel_data(backup_root):
    """Restore Sentinel templates and data"""
    sentinel_dir = backup_root / "sentinel"
    if not sentinel_dir.exists():
        logger.info("[restore] No Sentinel backup found")
        return
    
    # Restore templates directory
    templates_backup = sentinel_dir / "templates"
    templates_target = Path("/share/jarvis_prime/sentinel_templates")
    
    if templates_backup.exists():
        templates_target.mkdir(parents=True, exist_ok=True)
        
        # Copy all template files
        for template_file in templates_backup.glob("*.json"):
            shutil.copy2(template_file, templates_target / template_file.name)
        
        template_count = len(list(templates_target.glob("*.json")))
        logger.info(f"[restore] ✓ Restored Sentinel templates: {template_count} files")


async def restore_backup(request):
    """Restore from a comprehensive tar.gz backup"""
    try:
        logger.info("[restore] Starting comprehensive backup restore")
        
        reader = await request.multipart()
        field = await reader.next()

        if not field or field.name != "backup":
            return web.json_response(
                {"error": "No backup file provided"},
                status=400
            )

        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp_file:
            tmp_path = Path(tmp_file.name)

            size = 0
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                tmp_file.write(chunk)
                size += len(chunk)

            logger.info(f"[restore] Received backup file: {size:,} bytes")

        # Extract and restore
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_dir = Path(tmpdir)

            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(extract_dir)

            logger.info(f"[restore] Extracted backup")

            backup_root = extract_dir / "jarvis_prime_backup"
            if not backup_root.exists():
                subdirs = list(extract_dir.iterdir())
                if len(subdirs) == 1 and subdirs[0].is_dir():
                    backup_root = subdirs[0]
                else:
                    raise Exception("Invalid backup structure")

            # Read manifest
            manifest_file = backup_root / "MANIFEST.json"
            if manifest_file.exists():
                with open(manifest_file) as f:
                    manifest = json.load(f)
                logger.info(f"[restore] Backup created: {manifest.get('created_at')}")
                logger.info(f"[restore] Contents: {json.dumps(manifest['backup_contents'], indent=2)}")

            # 1. Restore database (binary)
            db_backup = backup_root / "jarvis.db"
            db_target = Path("/data/jarvis.db")
            if db_backup.exists():
                if db_target.exists():
                    shutil.copy2(db_target, db_target.with_suffix(".db.bak"))
                shutil.copy2(db_backup, db_target)
                logger.info("[restore] ✓ Restored database binary")

            # 2. Restore database tables from JSON (for additional data)
            restore_database_tables(backup_root)

            # 3. Restore Sentinel data
            restore_sentinel_data(backup_root)

            # 4. Restore playbooks
            playbooks_backup = backup_root / "playbooks"
            playbooks_target = Path("/share/jarvis_prime/playbooks")
            if playbooks_backup.exists():
                playbooks_target.mkdir(parents=True, exist_ok=True)
                for playbook in playbooks_backup.glob("*"):
                    shutil.copy2(playbook, playbooks_target / playbook.name)
                logger.info(f"[restore] ✓ Restored playbooks")

            # 5. Restore models
            models_backup = backup_root / "models"
            models_target = Path("/share/jarvis_prime/models")
            if models_backup.exists():
                models_target.mkdir(parents=True, exist_ok=True)
                for model in models_backup.glob("*"):
                    if model.is_file():
                        shutil.copy2(model, models_target / model.name)
                logger.info(f"[restore] ✓ Restored models")

            # 6. Restore config
            config_backup = backup_root / "config.yaml"
            config_target = Path("/share/jarvis_prime/config.yaml")
            if config_backup.exists():
                shutil.copy2(config_backup, config_target)
                logger.info("[restore] ✓ Restored config")

            # 7. Restore options.json
            options_backup = backup_root / "orchestrator/options.json"
            options_target = Path("/data/options.json")
            if options_backup.exists():
                shutil.copy2(options_backup, options_target)
                logger.info("[restore] ✓ Restored options.json")

        tmp_path.unlink(missing_ok=True)
        
        logger.info("[restore] === RESTORE COMPLETE ===")
        logger.info("[restore] Jarvis Prime will restart to apply changes")
        
        return web.json_response({
            "success": True,
            "message": "Backup restored successfully. System will restart."
        })

    except Exception as e:
        logger.error(f"[restore] ✗ FAILED to restore backup: {e}")
        logger.error(f"[restore] Traceback:\n{traceback.format_exc()}")
        return web.json_response(
            {"error": f"Restore failed: {str(e)}"},
            status=500
        )


def register_routes(app):
    """Register backup/restore routes"""
    app.router.add_post("/api/backup/create", create_backup)
    app.router.add_post("/api/backup/restore", restore_backup)
