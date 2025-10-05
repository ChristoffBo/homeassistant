#!/usr/bin/env python3
# /app/orchestrator.py
# Sprint 4: Cancel jobs, job names in history, retry support
# FIXED: Notification flag handling + Multiple group support

import os
import json
import sqlite3
import subprocess
import asyncio
import signal
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import web
import logging

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config, db_path, notify_callback=None, logger=None):
        self.config = config
        self.db_path = db_path
        self.notify_callback = notify_callback
        self.logger = logger or print
        self.playbooks_path = config.get("playbooks_path", "/share/jarvis_prime/playbooks")
        self.runner = config.get("runner", "script")
        self.ws_clients = set()
        self._scheduler_task = None
        self.init_db()
        
    def start_scheduler(self):
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            self.logger("[orchestrator] Scheduler started")
    
    async def _scheduler_loop(self):
        while True:
            try:
                await asyncio.sleep(60)
                await self._check_schedules()
            except Exception as e:
                self.logger(f"[orchestrator] Scheduler error: {e}")
    
    async def _check_schedules(self):
        now = datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_schedules WHERE enabled = 1")
            schedules = [dict(row) for row in cursor.fetchall()]
        
        for schedule in schedules:
            next_run = schedule.get("next_run")
            if next_run:
                next_run_dt = datetime.fromisoformat(next_run)
                if now >= next_run_dt:
                    self.logger(f"[orchestrator] Triggering scheduled job: {schedule['playbook']}")
                    self.run_playbook(
                        schedule['playbook'], 
                        triggered_by=f"schedule_{schedule['id']}", 
                        inventory_group=schedule.get('inventory_group'),
                        job_name=schedule.get('name')
                    )
                    self._update_schedule_run_time(schedule['id'], schedule['cron'])

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orchestration_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT,
                    playbook TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    started_at TEXT,
                    completed_at TEXT,
                    output TEXT,
                    exit_code INTEGER,
                    triggered_by TEXT,
                    inventory_group TEXT,
                    pid INTEGER
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orchestration_servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    hostname TEXT NOT NULL,
                    port INTEGER DEFAULT 22,
                    username TEXT NOT NULL,
                    password TEXT,
                    groups TEXT,
                    description TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orchestration_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    playbook TEXT NOT NULL,
                    cron TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    notify_on_completion INTEGER DEFAULT 1,
                    inventory_group TEXT,
                    last_run TEXT,
                    next_run TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # Add missing columns if they don't exist
            try:
                cursor.execute("SELECT notify_on_completion FROM orchestration_schedules LIMIT 1")
            except sqlite3.OperationalError:
                self.logger("[orchestrator] Adding notify_on_completion column")
                cursor.execute("ALTER TABLE orchestration_schedules ADD COLUMN notify_on_completion INTEGER DEFAULT 1")
            
            try:
                cursor.execute("SELECT name FROM orchestration_schedules LIMIT 1")
            except sqlite3.OperationalError:
                self.logger("[orchestrator] Adding name column to schedules")
                cursor.execute("ALTER TABLE orchestration_schedules ADD COLUMN name TEXT")
            
            try:
                cursor.execute("SELECT job_name FROM orchestration_jobs LIMIT 1")
            except sqlite3.OperationalError:
                self.logger("[orchestrator] Adding job_name column to jobs")
                cursor.execute("ALTER TABLE orchestration_jobs ADD COLUMN job_name TEXT")
            
            try:
                cursor.execute("SELECT inventory_group FROM orchestration_jobs LIMIT 1")
            except sqlite3.OperationalError:
                self.logger("[orchestrator] Adding inventory_group column to jobs")
                cursor.execute("ALTER TABLE orchestration_jobs ADD COLUMN inventory_group TEXT")
            
            conn.commit()

    def _update_schedule_run_time(self, schedule_id, cron_expr):
        now = datetime.now()
        next_run = self._calculate_next_run(cron_expr, now)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE orchestration_schedules 
                SET last_run = ?, next_run = ?, updated_at = ?
                WHERE id = ?
            """, (now.isoformat(), next_run.isoformat() if next_run else None, now.isoformat(), schedule_id))
            conn.commit()
    
    def _calculate_next_run(self, cron_expr, from_time):
        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return None
            
            minute, hour, day, month, weekday = parts
            next_time = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
            
            for _ in range(525600):
                if self._cron_matches(next_time, minute, hour, day, month, weekday):
                    return next_time
                next_time += timedelta(minutes=1)
            
            return None
        except Exception:
            return None
    
    def _cron_matches(self, dt, minute, hour, day, month, weekday):
        if minute != '*' and int(minute) != dt.minute:
            return False
        if hour != '*' and int(hour) != dt.hour:
            return False
        if day != '*' and int(day) != dt.day:
            return False
        if month != '*' and int(month) != dt.month:
            return False
        if weekday != '*' and int(weekday) != dt.weekday():
            return False
        return True
    
    def add_schedule(self, name, playbook, cron, inventory_group=None, enabled=True, notify_on_completion=True):
        now = datetime.now()
        next_run = self._calculate_next_run(cron, now)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orchestration_schedules 
                (name, playbook, cron, enabled, notify_on_completion, inventory_group, next_run, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, playbook, cron, 1 if enabled else 0, 1 if notify_on_completion else 0, inventory_group, 
                  next_run.isoformat() if next_run else None, now.isoformat(), now.isoformat()))
            conn.commit()
            return cursor.lastrowid
    
    def list_schedules(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_schedules ORDER BY playbook")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_schedule(self, schedule_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_schedules WHERE id = ?", (schedule_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_schedule(self, schedule_id, **kwargs):
        allowed_fields = ["name", "playbook", "cron", "enabled", "notify_on_completion", "inventory_group"]
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not updates:
            return False
        
        if "cron" in updates:
            next_run = self._calculate_next_run(updates["cron"], datetime.now())
            updates["next_run"] = next_run.isoformat() if next_run else None
        
        updates["updated_at"] = datetime.now().isoformat()
        fields = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [schedule_id]
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE orchestration_schedules SET {fields} WHERE id = ?", values)
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_schedule(self, schedule_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM orchestration_schedules WHERE id = ?", (schedule_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_playbooks(self):
        playbooks = []
        playbooks_dir = Path(self.playbooks_path)

        if not playbooks_dir.exists():
            playbooks_dir.mkdir(parents=True, exist_ok=True)
            return playbooks

        extensions = ["*.sh", "*.py", "*.yml", "*.yaml"]
        for ext in extensions:
            for playbook in playbooks_dir.glob(ext):
                playbooks.append({
                    "name": playbook.name,
                    "path": str(playbook),
                    "type": playbook.suffix[1:],
                    "size": playbook.stat().st_size,
                    "modified": datetime.fromtimestamp(playbook.stat().st_mtime).isoformat()
                })

        return sorted(playbooks, key=lambda x: x["name"])

    def list_playbooks_organized(self):
        playbooks_dir = Path(self.playbooks_path)
        
        if not playbooks_dir.exists():
            playbooks_dir.mkdir(parents=True, exist_ok=True)
            return {}
        
        organized = {}
        extensions = [".sh", ".py", ".yml", ".yaml"]
        
        for item in playbooks_dir.rglob("*"):
            if item.is_file() and item.suffix.lower() in extensions:
                rel_path = item.relative_to(playbooks_dir)
                
                if len(rel_path.parts) > 1:
                    category = rel_path.parts[0]
                else:
                    category = "root"
                
                if category not in organized:
                    organized[category] = []
                
                organized[category].append({
                    "name": item.name,
                    "path": str(rel_path),
                    "full_path": str(item),
                    "type": item.suffix[1:],
                    "size": item.stat().st_size,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                })
        
        for category in organized:
            organized[category].sort(key=lambda x: x["name"])
        
        return organized

    def get_job_history(self, limit=50, status=None, playbook=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM orchestration_jobs WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            if playbook:
                query += " AND playbook LIKE ?"
                params.append(f"%{playbook}%")
            
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def purge_history(self, criteria):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if criteria == "all":
                cursor.execute("DELETE FROM orchestration_jobs")
            elif criteria == "failed":
                cursor.execute("DELETE FROM orchestration_jobs WHERE status = 'failed'")
            elif criteria == "completed":
                cursor.execute("DELETE FROM orchestration_jobs WHERE status = 'completed'")
            elif criteria.startswith("older_than_"):
                days = int(criteria.split("_")[-1])
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                cursor.execute("DELETE FROM orchestration_jobs WHERE started_at < ?", (cutoff,))
            
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def get_history_stats(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as count FROM orchestration_jobs")
            total = cursor.fetchone()["count"]
            
            cursor.execute("SELECT MIN(started_at) as oldest FROM orchestration_jobs")
            oldest = cursor.fetchone()["oldest"]
            
            cursor.execute("SELECT SUM(LENGTH(output)) as size FROM orchestration_jobs")
            size_bytes = cursor.fetchone()["size"] or 0
            size_mb = round(size_bytes / (1024 * 1024), 2)
            
            return {
                "total_entries": total,
                "oldest_entry": oldest,
                "size_mb": size_mb
            }

    def add_server(self, name, hostname, username, password, port=22, groups="", description=""):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO orchestration_servers 
                (name, hostname, port, username, password, groups, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, hostname, port, username, password, groups, description, now, now))
            conn.commit()
            return cursor.lastrowid

    def update_server(self, server_id, **kwargs):
        allowed_fields = ["name", "hostname", "port", "username", "password", "groups", "description"]
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not updates:
            return False
        
        updates["updated_at"] = datetime.now().isoformat()
        fields = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [server_id]
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE orchestration_servers SET {fields} WHERE id = ?", values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_server(self, server_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM orchestration_servers WHERE id = ?", (server_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_servers(self, group=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if group:
                cursor.execute("SELECT * FROM orchestration_servers WHERE groups LIKE ? ORDER BY name", (f"%{group}%",))
            else:
                cursor.execute("SELECT * FROM orchestration_servers ORDER BY name")
            servers = [dict(row) for row in cursor.fetchall()]
            for server in servers:
                server["has_password"] = bool(server.get("password"))
                server.pop("password", None)
            return servers

    def get_server(self, server_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_servers WHERE id = ?", (server_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def generate_ansible_inventory(self, group=None):
        """Generate Ansible inventory, supporting comma-separated groups"""
        
        # Handle multiple comma-separated groups (FIXED)
        if group and ',' in group:
            groups_to_search = [g.strip() for g in group.split(',') if g.strip()]
            servers_set = {}  # Use dict to avoid duplicates by ID
            
            # Get servers from each group
            for single_group in groups_to_search:
                group_servers = self.list_servers(single_group)
                for s in group_servers:
                    if s['id'] not in servers_set:
                        # Get full server object with password
                        full_server = self.get_server(s['id'])
                        if full_server:
                            servers_set[s['id']] = full_server
            
            servers = list(servers_set.values())
        else:
            # Single group or all servers
            servers_list = self.list_servers(group)
            # Get full server objects with passwords
            servers = []
            for s in servers_list:
                full_server = self.get_server(s['id'])
                if full_server:
                    servers.append(full_server)
        
        if not servers:
            self.logger(f"[orchestrator] No servers found for group: {group}")
            return ""  # Empty inventory
        
        # Build groups dictionary
        groups_dict = {}
        for server in servers:
            server_groups = [g.strip() for g in server.get("groups", "").split(",") if g.strip()]
            if not server_groups:
                server_groups = ["ungrouped"]
            
            for grp in server_groups:
                if grp not in groups_dict:
                    groups_dict[grp] = []
                groups_dict[grp].append(server)
        
        # Generate inventory
        inventory_lines = []
        for grp, srvs in sorted(groups_dict.items()):
            inventory_lines.append(f"[{grp}]")
            for srv in srvs:
                line = f"{srv['name']} ansible_host={srv['hostname']} ansible_port={srv['port']} ansible_user={srv['username']}"
                if srv.get("password"):
                    line += f" ansible_ssh_pass={srv['password']}"
                inventory_lines.append(line)
            inventory_lines.append("")
        
        inventory_text = "\n".join(inventory_lines)
        self.logger(f"[orchestrator] Generated inventory for {len(servers)} servers in {len(groups_dict)} groups")
        return inventory_text

    def get_job_status(self, job_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def cancel_job(self, job_id, pid):
        """Cancel a running job by killing its process"""
        try:
            if pid and pid > 0:
                os.kill(pid, signal.SIGTERM)
                self.logger(f"[orchestrator] Sent SIGTERM to job {job_id} (PID: {pid})")
                
                # Update job status
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE orchestration_jobs
                        SET status = 'cancelled', completed_at = ?, exit_code = -1
                        WHERE id = ?
                    """, (datetime.now().isoformat(), job_id))
                    conn.commit()
                
                return True
            return False
        except ProcessLookupError:
            self.logger(f"[orchestrator] Process {pid} not found")
            return False
        except Exception as e:
            self.logger(f"[orchestrator] Error cancelling job: {e}")
            return False

    def run_playbook(self, playbook_name, triggered_by="manual", inventory_group=None, job_name=None):
        """Execute a playbook asynchronously"""
        started_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orchestration_jobs (job_name, playbook, status, started_at, triggered_by, inventory_group)
                VALUES (?, ?, 'running', ?, ?, ?)
            """, (job_name, playbook_name, started_at, triggered_by, inventory_group))
            job_id = cursor.lastrowid
            conn.commit()

        asyncio.create_task(self._execute_playbook(job_id, playbook_name, inventory_group, triggered_by))

        return job_id

    async def _execute_playbook(self, job_id, playbook_name, inventory_group=None, triggered_by="manual"):
        base_path = Path(self.playbooks_path).resolve()
        playbook_path = (base_path / playbook_name).resolve()

        if not str(playbook_path).startswith(str(base_path)):
            self._update_job(job_id, "failed", "Invalid playbook path", -1, None)
            return

        if not playbook_path.exists():
            self._update_job(job_id, "failed", "Playbook not found", -1, None)
            return

        try:
            ext = playbook_path.suffix.lower()
            
            if ext in [".yml", ".yaml"] and self.runner == "ansible":
                inventory_content = self.generate_ansible_inventory(inventory_group)
                
                if not inventory_content:
                    self._update_job(job_id, "failed", f"No hosts matched for group: {inventory_group}", -1, None)
                    return
                
                inventory_path = base_path / f".inventory_{job_id}.ini"
                
                with open(inventory_path, "w") as f:
                    f.write(inventory_content)
                
                self.logger(f"[orchestrator] Inventory file created: {inventory_path}")
                
                cmd = [
                    "ansible-playbook",
                    "-i", str(inventory_path),
                    str(playbook_path)
                ]
                
                env = os.environ.copy()
                env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
                env["ANSIBLE_SSH_PIPELINING"] = "False"
            
            elif ext == ".sh":
                cmd = ["bash", str(playbook_path)]
                env = None
            elif ext == ".py":
                cmd = ["python3", str(playbook_path)]
                env = None
            else:
                self._update_job(job_id, "failed", f"Unsupported file type: {ext}", -1, None)
                return

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env
            )

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE orchestration_jobs SET pid = ? WHERE id = ?", (process.pid, job_id))
                conn.commit()

            output_lines = []
            
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode('utf-8', errors='replace').rstrip()
                output_lines.append(line)
                
                await self._broadcast_log(job_id, line)

            await process.wait()
            exit_code = process.returncode
            output = "\n".join(output_lines)

            status = "completed" if exit_code == 0 else "failed"
            self._update_job(job_id, status, output, exit_code, process.pid)
            self._send_notification(job_id, playbook_name, status, exit_code, triggered_by=triggered_by)

            if ext in [".yml", ".yaml"] and self.runner == "ansible":
                try:
                    inventory_path.unlink()
                except Exception:
                    pass

        except Exception as e:
            msg = f"Execution error: {e}"
            self._update_job(job_id, "failed", msg, -1, None)
            self._send_notification(job_id, playbook_name, "failed", -1, triggered_by=triggered_by, error=msg)

    async def _broadcast_log(self, job_id, line):
        if not self.ws_clients:
            return
        
        msg = json.dumps({"event": "orchestration_log", "job_id": job_id, "line": line})
        dead = []
        
        for ws in list(self.ws_clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.append(ws)
        
        for ws in dead:
            self.ws_clients.discard(ws)

    def _update_job(self, job_id, status, output, exit_code, pid):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE orchestration_jobs
                SET status = ?, completed_at = ?, output = ?, exit_code = ?, pid = ?
                WHERE id = ?
            """, (status, datetime.now().isoformat(), output, exit_code, pid, job_id))
            conn.commit()

    def _send_notification(self, job_id, playbook_name, status, exit_code, triggered_by="manual", error=None):
        """Send notification respecting the notify_on_completion flag (FIXED)"""
        
        # Check if this is a scheduled job with notifications disabled
        if triggered_by.startswith("schedule_"):
            try:
                schedule_id = int(triggered_by.split("_")[1])
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT notify_on_completion FROM orchestration_schedules WHERE id = ?", (schedule_id,))
                    row = cursor.fetchone()
                    if row:
                        # Explicit int conversion to handle SQLite boolean storage
                        notify_flag = int(row["notify_on_completion"]) if row["notify_on_completion"] is not None else 1
                        
                        if notify_flag == 0:
                            # OPTION 1: Skip ALL notifications when flag is disabled
                            self.logger(f"[orchestrator] Skipping notification for job {job_id} (notify_on_completion=False)")
                            return
                            
                            # OPTION 2: Only skip successful notifications, always notify on failure
                            # Uncomment below and comment out the return above to use this option:
                            # if status != "failed":
                            #     self.logger(f"[orchestrator] Skipping success notification for job {job_id}")
                            #     return
            except Exception as e:
                self.logger(f"[orchestrator] Error checking notification flag: {e}")
        
        # Build notification message
        title = "Orchestrator"
        
        if status == "completed":
            body = f"✅ {playbook_name} completed successfully (exit code: {exit_code})"
            priority = 3
        else:
            if error:
                body = f"❌ {playbook_name} FAILED – {error}"
            else:
                body = f"❌ {playbook_name} FAILED (exit code: {exit_code})"
            priority = 5
        
        # Send notification
        try:
            from bot import process_incoming
            process_incoming(title, body, source="orchestrator", priority=priority)
            self.logger(f"[orchestrator] Notification sent for job {job_id}: {status}")
        except Exception as e:
            logger.error(f"process_incoming not available: {e}")
            try:
                from errors import notify_error
                notify_error(f"[Orchestrator] {body}", context="orchestrator")
            except Exception:
                pass
        
        
orchestrator = None

def init_orchestrator(config, db_path, notify_callback=None, logger=None):
    global orchestrator
    orchestrator = Orchestrator(config, db_path, notify_callback, logger)
    return orchestrator

def start_orchestrator_scheduler():
    if orchestrator:
        orchestrator.start_scheduler()

def _json(data, status=200):
    return web.Response(text=json.dumps(data, ensure_ascii=False), status=status, content_type="application/json")

async def api_list_playbooks(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    return _json({"playbooks": orchestrator.list_playbooks()})

async def api_list_playbooks_organized(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    return _json({"playbooks": orchestrator.list_playbooks_organized()})

async def api_upload_playbook(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    try:
        reader = await request.multipart()
        field = await reader.next()
        
        if field.name != 'file':
            return _json({"error": "Expected 'file' field"}, status=400)
        
        filename = field.filename
        if not filename:
            return _json({"error": "No filename provided"}, status=400)
        
        valid_extensions = ['.yml', '.yaml', '.sh', '.py']
        ext = Path(filename).suffix.lower()
        if ext not in valid_extensions:
            return _json({"error": f"Invalid file type. Allowed: {', '.join(valid_extensions)}"}, status=400)
        
        safe_filename = Path(filename).name
        playbooks_dir = Path(orchestrator.playbooks_path)
        playbooks_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = playbooks_dir / safe_filename
        
        size = 0
        with open(file_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
        
        return _json({
            "success": True, 
            "filename": safe_filename,
            "size": size,
            "path": str(file_path.relative_to(playbooks_dir))
        })
    
    except Exception as e:
        return _json({"error": str(e)}, status=500)

async def api_download_playbook(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    try:
        playbook_path = request.match_info["playbook"]
        base_path = Path(orchestrator.playbooks_path).resolve()
        full_path = (base_path / playbook_path).resolve()
        
        if not str(full_path).startswith(str(base_path)):
            return _json({"error": "Invalid path"}, status=400)
        
        if not full_path.exists() or not full_path.is_file():
            return _json({"error": "File not found"}, status=404)
        
        return web.FileResponse(
            path=str(full_path),
            headers={
                'Content-Disposition': f'attachment; filename="{full_path.name}"'
            }
        )
    
    except Exception as e:
        return _json({"error": str(e)}, status=500)

async def api_run_playbook(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    playbook = request.match_info["playbook"]
    try:
        data = await request.json()
    except Exception:
        data = {}
    
    triggered_by = data.get("triggered_by", "manual")
    inventory_group = data.get("inventory_group")
    job_name = data.get("job_name")
    
    try:
        job_id = orchestrator.run_playbook(playbook, triggered_by, inventory_group, job_name)
        return _json({"success": True, "job_id": job_id, "message": f"Playbook {playbook} started"})
    except Exception as e:
        return _json({"error": str(e)}, status=500)

async def api_cancel_job(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    job_id = int(request.match_info["id"])
    
    try:
        data = await request.json()
        pid = data.get("pid", 0)
    except Exception:
        pid = 0
    
    try:
        success = orchestrator.cancel_job(job_id, pid)
        if success:
            return _json({"success": True, "message": "Job cancelled"})
        return _json({"error": "Failed to cancel job"}, status=400)
    except Exception as e:
        return _json({"error": str(e)}, status=500)

async def api_get_status(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    job_id = int(request.match_info["id"])
    job = orchestrator.get_job_status(job_id)
    
    if job:
        return _json(job)
    return _json({"error": "Job not found"}, status=404)

async def api_history(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    try:
        limit = int(request.rel_url.query.get("limit", "50"))
        status = request.rel_url.query.get("status")
        playbook = request.rel_url.query.get("playbook")
    except Exception:
        limit = 50
        status = None
        playbook = None
    
    return _json({"jobs": orchestrator.get_job_history(limit, status, playbook)})

async def api_purge_history(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    try:
        data = await request.json()
        criteria = data.get("criteria", "all")
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    try:
        deleted = orchestrator.purge_history(criteria)
        return _json({"success": True, "deleted": deleted})
    except Exception as e:
        return _json({"error": str(e)}, status=500)

async def api_history_stats(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    return _json(orchestrator.get_history_stats())

async def api_list_servers(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    group = request.rel_url.query.get("group")
    return _json({"servers": orchestrator.list_servers(group)})

async def api_get_server(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    server_id = int(request.match_info["id"])
    server = orchestrator.get_server(server_id)
    
    if server:
        return _json(server)
    return _json({"error": "Server not found"}, status=404)

async def api_add_server(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    try:
        server_id = orchestrator.add_server(
            name=data["name"],
            hostname=data["hostname"],
            username=data["username"],
            password=data.get("password", ""),
            port=data.get("port", 22),
            groups=data.get("groups", ""),
            description=data.get("description", "")
        )
        return _json({"success": True, "server_id": server_id})
    except Exception as e:
        return _json({"error": str(e)}, status=400)

async def api_update_server(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    server_id = int(request.match_info["id"])
    
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    try:
        success = orchestrator.update_server(server_id, **data)
        if success:
            return _json({"success": True})
        return _json({"error": "Server not found"}, status=404)
    except Exception as e:
        return _json({"error": str(e)}, status=400)

async def api_delete_server(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    server_id = int(request.match_info["id"])
    
    try:
        success = orchestrator.delete_server(server_id)
        if success:
            return _json({"success": True})
        return _json({"error": "Server not found"}, status=404)
    except Exception as e:
        return _json({"error": str(e)}, status=400)

async def api_websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    if orchestrator:
        orchestrator.ws_clients.add(ws)
    
    try:
        async for msg in ws:
            pass
    finally:
        if orchestrator:
            orchestrator.ws_clients.discard(ws)
    
    return ws

async def api_list_schedules(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    return _json({"schedules": orchestrator.list_schedules()})

async def api_get_schedule(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    schedule_id = int(request.match_info["id"])
    schedule = orchestrator.get_schedule(schedule_id)
    
    if schedule:
        return _json(schedule)
    return _json({"error": "Schedule not found"}, status=404)

async def api_add_schedule(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    try:
        schedule_id = orchestrator.add_schedule(
            name=data.get("name", "Unnamed Schedule"),
            playbook=data["playbook"],
            cron=data["cron"],
            inventory_group=data.get("inventory_group"),
            enabled=data.get("enabled", True),
            notify_on_completion=data.get("notify_on_completion", True)
        )
        return _json({"success": True, "schedule_id": schedule_id})
    except Exception as e:
        return _json({"error": str(e)}, status=400)

async def api_update_schedule(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    schedule_id = int(request.match_info["id"])
    
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    try:
        success = orchestrator.update_schedule(schedule_id, **data)
        if success:
            return _json({"success": True})
        return _json({"error": "Schedule not found"}, status=404)
    except Exception as e:
        return _json({"error": str(e)}, status=400)

async def api_delete_schedule(request):
    if not orchestrator:
        return _json({"error": "Orchestrator not initialized"}, status=500)
    
    schedule_id = int(request.match_info["id"])
    
    try:
        success = orchestrator.delete_schedule(schedule_id)
        if success:
            return _json({"success": True})
        return _json({"error": "Schedule not found"}, status=404)
    except Exception as e:
        return _json({"error": str(e)}, status=400)

def register_routes(app):
    app.router.add_get("/api/orchestrator/playbooks", api_list_playbooks)
    app.router.add_get("/api/orchestrator/playbooks/organized", api_list_playbooks_organized)
    app.router.add_post("/api/orchestrator/playbooks/upload", api_upload_playbook)
    app.router.add_get("/api/orchestrator/playbooks/download/{playbook:.*}", api_download_playbook)
    app.router.add_post("/api/orchestrator/run/{playbook:.*}", api_run_playbook)
    app.router.add_get("/api/orchestrator/status/{id:\\d+}", api_get_status)
    app.router.add_post("/api/orchestrator/jobs/{id:\\d+}/cancel", api_cancel_job)
    app.router.add_get("/api/orchestrator/history", api_history)
    app.router.add_post("/api/orchestrator/history/purge", api_purge_history)
    app.router.add_get("/api/orchestrator/history/stats", api_history_stats)
    app.router.add_get("/api/orchestrator/servers", api_list_servers)
    app.router.add_get("/api/orchestrator/servers/{id:\\d+}", api_get_server)
    app.router.add_post("/api/orchestrator/servers", api_add_server)
    app.router.add_put("/api/orchestrator/servers/{id:\\d+}", api_update_server)
    app.router.add_delete("/api/orchestrator/servers/{id:\\d+}", api_delete_server)
    app.router.add_get("/api/orchestrator/schedules", api_list_schedules)
    app.router.add_get("/api/orchestrator/schedules/{id:\\d+}", api_get_schedule)
    app.router.add_post("/api/orchestrator/schedules", api_add_schedule)
    app.router.add_put("/api/orchestrator/schedules/{id:\\d+}", api_update_schedule)
    app.router.add_delete("/api/orchestrator/schedules/{id:\\d+}", api_delete_schedule)
    app.router.add_get("/api/orchestrator/ws", api_websocket)
