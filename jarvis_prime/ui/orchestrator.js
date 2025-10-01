#!/usr/bin/env python3
# /app/orchestrator.py
#
# Orchestrator: Lightweight automation module for Jarvis Prime
# Runs playbooks/scripts, manages servers, logs results, notifies on completion
# Built for aiohttp

import os
import json
import sqlite3
import subprocess
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import web

class Orchestrator:
    def __init__(self, config, db_path, notify_callback=None, logger=None):
        self.config = config
        self.db_path = db_path
        self.notify_callback = notify_callback
        self.logger = logger or print
        self.playbooks_path = config.get("playbooks_path", "/share/jarvis_prime/playbooks")
        self.runner = config.get("runner", "script")
        self.ws_clients = set()  # WebSocket clients for live logs
        self._scheduler_task = None
        self.init_db()
        
    def start_scheduler(self):
        """Start the background scheduler task"""
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            self.logger("[orchestrator] Scheduler started")
    
    async def _scheduler_loop(self):
        """Background loop that checks for scheduled jobs every minute"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._check_schedules()
            except Exception as e:
                self.logger(f"[orchestrator] Scheduler error: {e}")
    
    async def _check_schedules(self):
        """Check if any scheduled jobs should run now"""
        now = datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM orchestration_schedules 
                WHERE enabled = 1
            """)
            schedules = [dict(row) for row in cursor.fetchall()]
        
        for schedule in schedules:
            next_run = schedule.get("next_run")
            if next_run:
                next_run_dt = datetime.fromisoformat(next_run)
                if now >= next_run_dt:
                    # Time to run this job
                    self.logger(f"[orchestrator] Triggering scheduled job: {schedule['playbook']}")
                    self.run_playbook(
                        schedule['playbook'], 
                        triggered_by=f"schedule_{schedule['id']}", 
                        inventory_group=schedule.get('inventory_group')
                    )
                    # Update last_run and calculate next_run
                    self._update_schedule_run_time(schedule['id'], schedule['cron'])

    def init_db(self):
        """Initialize database tables for job tracking"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orchestration_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playbook TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    started_at TEXT,
                    completed_at TEXT,
                    output TEXT,
                    exit_code INTEGER,
                    triggered_by TEXT,
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
            
            # Auto-migration: Add notify_on_completion column if it doesn't exist
            try:
                cursor.execute("SELECT notify_on_completion FROM orchestration_schedules LIMIT 1")
            except sqlite3.OperationalError:
                self.logger("[orchestrator] Adding notify_on_completion column to schedules table")
                cursor.execute("ALTER TABLE orchestration_schedules ADD COLUMN notify_on_completion INTEGER DEFAULT 1")
            
            # Auto-migration: Add name column if it doesn't exist
            try:
                cursor.execute("SELECT name FROM orchestration_schedules LIMIT 1")
            except sqlite3.OperationalError:
                self.logger("[orchestrator] Adding name column to schedules table")
                cursor.execute("ALTER TABLE orchestration_schedules ADD COLUMN name TEXT")
            
            conn.commit()

    def _update_schedule_run_time(self, schedule_id, cron_expr):
        """Update last_run and calculate next_run based on cron expression"""
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
        """Simple cron parser - supports: minute hour day month weekday"""
        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return None
            
            minute, hour, day, month, weekday = parts
            
            # Start from next minute
            next_time = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
            
            # Check up to 366 days in the future
            for _ in range(525600):  # minutes in a year
                if self._cron_matches(next_time, minute, hour, day, month, weekday):
                    return next_time
                next_time += timedelta(minutes=1)
            
            return None
        except Exception:
            return None
    
    def _cron_matches(self, dt, minute, hour, day, month, weekday):
        """Check if datetime matches cron expression"""
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
        """Add a new schedule for a playbook"""
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
        """List all schedules"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_schedules ORDER BY playbook")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_schedule(self, schedule_id):
        """Get a specific schedule by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_schedules WHERE id = ?", (schedule_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_schedule(self, schedule_id, **kwargs):
        """Update schedule details"""
        allowed_fields = ["name", "playbook", "cron", "enabled", "notify_on_completion", "inventory_group"]
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not updates:
            return False
        
        # Recalculate next_run if cron changed
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
        """Delete a schedule"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM orchestration_schedules WHERE id = ?", (schedule_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_playbooks(self):
        """List all available playbooks from the playbooks directory (flat list)"""
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
        """List all playbooks organized by subdirectory for the new UI"""
        playbooks_dir = Path(self.playbooks_path)
        
        if not playbooks_dir.exists():
            playbooks_dir.mkdir(parents=True, exist_ok=True)
            return {}
        
        organized = {}
        extensions = [".sh", ".py", ".yml", ".yaml"]
        
        # Recursively scan directories
        for item in playbooks_dir.rglob("*"):
            if item.is_file() and item.suffix.lower() in extensions:
                # Get relative path from playbooks root
                rel_path = item.relative_to(playbooks_dir)
                
                # Determine category (parent directory name)
                if len(rel_path.parts) > 1:
                    category = rel_path.parts[0]  # e.g., "lxc", "debian"
                else:
                    category = "root"  # Files directly in playbooks/
                
                if category not in organized:
                    organized[category] = []
                
                organized[category].append({
                    "name": item.name,
                    "path": str(rel_path),  # Relative path for execution
                    "full_path": str(item),
                    "type": item.suffix[1:],
                    "size": item.stat().st_size,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                })
        
        # Sort playbooks within each category
        for category in organized:
            organized[category].sort(key=lambda x: x["name"])
        
        return organized

    def get_job_history(self, limit=50, status=None, playbook=None):
        """Get recent job execution history with optional filters"""
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
        """Purge history based on criteria"""
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
        """Get statistics about job history"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as count FROM orchestration_jobs")
            total = cursor.fetchone()["count"]
            
            cursor.execute("SELECT MIN(started_at) as oldest FROM orchestration_jobs")
            oldest = cursor.fetchone()["oldest"]
            
            # Estimate size (rough)
            cursor.execute("SELECT SUM(LENGTH(output)) as size FROM orchestration_jobs")
            size_bytes = cursor.fetchone()["size"] or 0
            size_mb = round(size_bytes / (1024 * 1024), 2)
            
            return {
                "total_entries": total,
                "oldest_entry": oldest,
                "size_mb": size_mb
            }

    def add_server(self, name, hostname, username, password, port=22, groups="", description=""):
        """Add a new server to inventory"""
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
        """Update server details"""
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
        """Delete a server from inventory"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM orchestration_servers WHERE id = ?", (server_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_servers(self, group=None):
        """List all servers, optionally filtered by group"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if group:
                cursor.execute("SELECT * FROM orchestration_servers WHERE groups LIKE ? ORDER BY name", (f"%{group}%",))
            else:
                cursor.execute("SELECT * FROM orchestration_servers ORDER BY name")
            servers = [dict(row) for row in cursor.fetchall()]
            # Don't expose passwords in list view
            for server in servers:
                server["has_password"] = bool(server.get("password"))
                server.pop("password", None)
            return servers

    def get_server(self, server_id):
        """Get a specific server by ID (includes password)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_servers WHERE id = ?", (server_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def generate_ansible_inventory(self, group=None):
        """Generate Ansible inventory file content from servers"""
        servers = self.list_servers(group)
        
        # Group servers by their groups
        groups_dict = {}
        for server in servers:
            server_groups = [g.strip() for g in server.get("groups", "").split(",") if g.strip()]
            if not server_groups:
                server_groups = ["ungrouped"]
            
            for grp in server_groups:
                if grp not in groups_dict:
                    groups_dict[grp] = []
                
                # Get full server details (with password)
                full_server = self.get_server(server["id"])
                groups_dict[grp].append(full_server)
        
        # Build INI-style inventory
        inventory_lines = []
        for grp, servers in sorted(groups_dict.items()):
            inventory_lines.append(f"[{grp}]")
            for srv in servers:
                line = f"{srv['name']} ansible_host={srv['hostname']} ansible_port={srv['port']} ansible_user={srv['username']}"
                if srv.get("password"):
                    line += f" ansible_ssh_pass={srv['password']}"
                inventory_lines.append(line)
            inventory_lines.append("")
        
        return "\n".join(inventory_lines)

    def get_job_status(self, job_id):
        """Get status of a specific job"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def run_playbook(self, playbook_name, triggered_by="manual", inventory_group=None):
        """Execute a playbook asynchronously"""
        started_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orchestration_jobs (playbook, status, started_at, triggered_by)
                VALUES (?, 'running', ?, ?)
            """, (playbook_name, started_at, triggered_by))
            job_id = cursor.lastrowid
            conn.commit()

        # Run in background asyncio task
        asyncio.create_task(self._execute_playbook(job_id, playbook_name, inventory_group, triggered_by))

        return job_id

    async def _execute_playbook(self, job_id, playbook_name, inventory_group=None, triggered_by="manual"):
        """Internal method to execute playbook and capture output"""
        base_path = Path(self.playbooks_path).resolve()
        playbook_path = (base_path / playbook_name).resolve()

        # Path traversal guard
        if not str(playbook_path).startswith(str(base_path)):
            self._update_job(job_id, "failed", "Invalid playbook path", -1, None)
            return

        if not playbook_path.exists():
            self._update_job(job_id, "failed", "Playbook not found", -1, None)
            return

        try:
            ext = playbook_path.suffix.lower()
            
            # For Ansible playbooks, generate inventory
            if ext in [".yml", ".yaml"] and self.runner == "ansible":
                # Generate temporary inventory file
                inventory_content = self.generate_ansible_inventory(inventory_group)
                inventory_path = base_path / f".inventory_{job_id}.ini"
                
                with open(inventory_path, "w") as f:
                    f.write(inventory_content)
                
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

            # Execute using asyncio subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env
            )

            # Store PID
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE orchestration_jobs SET pid = ? WHERE id = ?", (process.pid, job_id))
                conn.commit()

            output_lines = []
            
            # Stream output
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode('utf-8', errors='replace').rstrip()
                output_lines.append(line)
                
                # Broadcast to WebSocket clients
                await self._broadcast_log(job_id, line)

            await process.wait()
            exit_code = process.returncode
            output = "\n".join(output_lines)

            status = "completed" if exit_code == 0 else "failed"
            self._update_job(job_id, status, output, exit_code, process.pid)
            self._send_notification(job_id, playbook_name, status, exit_code, triggered_by=triggered_by)

            # Cleanup temporary inventory file
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
        """Broadcast log line to all connected WebSocket clients"""
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
        """Update job record in database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE orchestration_jobs
                SET status = ?, completed_at = ?, output = ?, exit_code = ?, pid = ?
                WHERE id = ?
            """, (status, datetime.now().isoformat(), output, exit_code, pid, job_id))
            conn.commit()

    def _send_notification(self, job_id, playbook_name, status, exit_code, triggered_by="manual", error=None):
        """Send notification via existing notify system"""
        if not self.notify_callback:
            return
        
        # Check if this was triggered by a schedule and if notifications are disabled
        if triggered_by.startswith("schedule_"):
            try:
                schedule_id = int(triggered_by.split("_")[1])
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT notify_on_completion FROM orchestration_schedules WHERE id = ?", (schedule_id,))
                    row = cursor.fetchone()
                    if row and not row["notify_on_completion"]:
                        # Notifications disabled for this schedule, skip unless it failed
                        if status != "failed":
                            return
            except Exception:
                pass  # If we can't check, send notification anyway

        status_emoji = "✅" if status == "completed" else "❌"
        title = f"{status_emoji} Playbook {status.upper()}"

        if error:
            message = f"Playbook: {playbook_name}\nStatus: {status}\nError: {error}"
        else:
            message = f"Playbook: {playbook_name}\nStatus: {status}\nExit Code: {exit_code}"

        try:
            self.notify_callback({
                "title": title,
                "message": message,
                "priority": "high" if status == "failed" else "normal",
                "tags": ["orchestration", playbook_name]
            })
        except Exception as e:
            self.logger(f"Failed to send notification: {e}")

# Global instance
orchestrator = None

def init_orchestrator(config, db_path, notify_callback=None, logger=None):
    """Initialize the orchestrator module"""
    global orchestrator
    orchestrator = Orchestrator(config, db_path, notify_callback, logger)
    return orchestrator

def start_orchestrator_scheduler():
    """Start the scheduler background task (call this after event loop is running)"""
    if orchestrator:
        orchestrator.start_scheduler()

# ---- aiohttp route handlers ----

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
    
    try:
        job_id = orchestrator.run_playbook(playbook, triggered_by, inventory_group)
        return _json({"success": True, "job_id": job_id, "message": f"Playbook {playbook} started"})
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
        return _json
// orchestrator.js - Orchestrator tab functionality for Jarvis Prime

(function() {
  'use strict';

  // Get API root from existing app.js
  function apiRoot() {
    if (window.JARVIS_API_BASE) {
      let v = String(window.JARVIS_API_BASE);
      return v.endsWith('/') ? v : v + '/';
    }
    try {
      const u = new URL(document.baseURI);
      let p = u.pathname;
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (p.endsWith('/ui/')) p = p.slice(0, -4);
      if (!p.endsWith('/')) p += '/';
      u.pathname = p;
      return u.toString();
    } catch (e) {
      return document.baseURI;
    }
  }

  const ROOT = apiRoot();
  const API = (path) => new URL(String(path).replace(/^\/+/, ''), ROOT).toString();

  // Toast helper (reuse from main app)
  function toast(msg, type = 'info') {
    const d = document.createElement('div');
    d.className = `toast ${type}`;
    d.textContent = msg;
    const container = document.getElementById('toast');
    if (container) {
      container.appendChild(d);
      setTimeout(() => d.remove(), 4000);
    }
  }

  // Enhanced fetch
  async function jfetch(url, opts = {}) {
    try {
      const r = await fetch(url, {
        ...opts,
        headers: {
          'Content-Type': 'application/json',
          ...opts.headers
        }
      });
      
      if (!r.ok) {
        const text = await r.text().catch(() => '');
        throw new Error(`${r.status} ${r.statusText}: ${text}`);
      }
      
      const ct = r.headers.get('content-type') || '';
      return ct.includes('application/json') ? r.json() : r.text();
    } catch (error) {
      console.error('Orchestrator API Error:', error);
      throw error;
    }
  }

  let currentJobId = null;
  let wsConnection = null;
  let editingScheduleId = null;

  // ============================================
  // ORCHESTRATOR SUB-TAB SWITCHING
  // ============================================
  document.querySelectorAll('.orch-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.orch-tab').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      
      document.querySelectorAll('.orch-panel').forEach(p => p.classList.remove('active'));
      const panelId = 'orch-' + btn.dataset.orchTab;
      const panel = document.getElementById(panelId);
      if (panel) panel.classList.add('active');

      // Load data when switching tabs
      const tab = btn.dataset.orchTab;
      if (tab === 'playbooks') orchLoadPlaybooks();
      else if (tab === 'servers') orchLoadServers();
      else if (tab === 'schedules') orchLoadSchedules();
      else if (tab === 'history') orchLoadHistory();
    });
  });

  // ============================================
  // WEBSOCKET FOR LIVE LOGS
  // ============================================
  function connectWebSocket() {
    try {
      const wsUrl = API('api/orchestrator/ws').replace('http://', 'ws://').replace('https://', 'wss://');
      wsConnection = new WebSocket(wsUrl);
      
      wsConnection.onopen = () => {
        console.log('[Orchestrator] WebSocket connected');
      };
      
      wsConnection.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event === 'orchestration_log' && data.job_id === currentJobId) {
            appendLog(data.line);
          }
        } catch (e) {
          console.error('WebSocket message parse error:', e);
        }
      };
      
      wsConnection.onerror = (error) => {
        console.error('[Orchestrator] WebSocket error:', error);
      };
      
      wsConnection.onclose = () => {
        console.log('[Orchestrator] WebSocket closed, reconnecting in 5s...');
        setTimeout(connectWebSocket, 5000);
      };
    } catch (e) {
      console.error('[Orchestrator] WebSocket connection failed:', e);
    }
  }

  function appendLog(line) {
    const logOutput = document.getElementById('orch-logs');
    if (!logOutput) return;
    
    const logLine = document.createElement('div');
    logLine.className = 'log-line';
    logLine.textContent = line;
    logOutput.appendChild(logLine);
    logOutput.scrollTop = logOutput.scrollHeight;
  }

  // ============================================
  // PLAYBOOKS - ORGANIZED BY CATEGORY
  // ============================================
  window.orchLoadPlaybooks = async function() {
    const container = document.getElementById('playbooks-list');
    if (!container) return;
    
    try {
      container.innerHTML = '<div class="text-center text-muted">Loading playbooks...</div>';
      const data = await jfetch(API('api/orchestrator/playbooks/organized'));
      
      if (!data.playbooks || Object.keys(data.playbooks).length === 0) {
        container.innerHTML = '<div class="text-center text-muted">No playbooks found. Add .sh, .py, or .yml files to /share/jarvis_prime/playbooks/</div>';
        return;
      }
      
      // Build organized playbook display
      let html = '';
      for (const [category, playbooks] of Object.entries(data.playbooks).sort()) {
        const categoryName = category === 'root' ? 'Root' : category.charAt(0).toUpperCase() + category.slice(1);
        const categoryIcon = {
          'lxc': '📦',
          'debian': '🐧',
          'proxmox': '🔧',
          'network': '🌐',
          'docker': '🐳',
          'security': '🔒',
          'root': '📁'
        }[category] || '📄';
        
        html += `<div class="playbook-category" style="margin-bottom: 24px;">
          <h4 style="color: var(--text-primary); margin-bottom: 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
            ${categoryIcon} ${categoryName}
          </h4>`;
        
        playbooks.forEach(p => {
          const safeId = p.path.replace(/[^a-zA-Z0-9]/g, '_');
          html += `
            <div class="playbook-card">
              <div class="playbook-name">${p.name}</div>
              <div class="playbook-meta">
                Type: ${p.type.toUpperCase()} | 
                Path: ${p.path} | 
                Modified: ${new Date(p.modified).toLocaleString()}
              </div>
              <div class="playbook-actions">
                <select class="playbook-target" id="target-${safeId}" style="margin-bottom: 8px;">
                  <option value="">All servers</option>
                </select>
                <button class="btn primary" onclick="orchRunPlaybook('${p.path.replace(/'/g, "\\'")}')">▶ Run</button>
              </div>
            </div>
          `;
        });
        
        html += '</div>';
      }
      
      container.innerHTML = html;
      
      // Load servers to populate dropdowns
      orchLoadServerOptionsForPlaybooks();
    } catch (e) {
      container.innerHTML = '<div class="text-center text-muted">Failed to load playbooks</div>';
      toast('Failed to load playbooks: ' + e.message, 'error');
    }
  };

  window.orchRefreshPlaybooks = orchLoadPlaybooks;

  // Load server options for playbook dropdowns
  async function orchLoadServerOptionsForPlaybooks() {
    try {
      const data = await jfetch(API('api/orchestrator/servers'));
      if (!data.servers) return;
      
      // Get unique groups and individual servers
      const groups = new Set();
      const servers = [];
      
      data.servers.forEach(s => {
        servers.push(s);
        if (s.groups) {
          s.groups.split(',').forEach(g => {
            const trimmed = g.trim();
            if (trimmed) groups.add(trimmed);
          });
        }
      });
      
      // Populate all playbook target dropdowns
      document.querySelectorAll('.playbook-target').forEach(select => {
        let options = '<option value="">All servers</option>';
        
        if (groups.size > 0) {
          options += '<optgroup label="Server Groups">';
          groups.forEach(g => {
            options += `<option value="group:${g}">${g} (group)</option>`;
          });
          options += '</optgroup>';
        }
        
        if (servers.length > 0) {
          options += '<optgroup label="Individual Servers">';
          servers.forEach(s => {
            options += `<option value="server:${s.name}">${s.name}</option>`;
          });
          options += '</optgroup>';
        }
        
        select.innerHTML = options;
      });
    } catch (e) {
      console.error('Failed to load server options:', e);
    }
  }

  window.orchRunPlaybook = async function(name) {
    try {
      // Get selected target from dropdown
      const safeId = name.replace(/[^a-zA-Z0-9]/g, '_');
      const targetSelect = document.getElementById(`target-${safeId}`);
      const target = targetSelect ? targetSelect.value : '';
      
      // Parse target
      let inventoryGroup = null;
      if (target.startsWith('group:')) {
        inventoryGroup = target.replace('group:', '');
      } else if (target.startsWith('server:')) {
        inventoryGroup = target.replace('server:', '');
      }
      
      // Clear logs
      const logOutput = document.getElementById('orch-logs');
      if (logOutput) logOutput.innerHTML = '';
      
      const response = await jfetch(API(`api/orchestrator/run/${encodeURIComponent(name)}`), {
        method: 'POST',
        body: JSON.stringify({ 
          triggered_by: 'web_ui',
          inventory_group: inventoryGroup
        })
      });
      
      if (response.success) {
        currentJobId = response.job_id;
        appendLog(`[JARVIS] Starting playbook: ${name} (Job ID: ${response.job_id})`);
        if (inventoryGroup) {
          appendLog(`[JARVIS] Target: ${inventoryGroup}`);
        } else {
          appendLog(`[JARVIS] Target: All servers`);
        }
        appendLog(`[JARVIS] Streaming output...\n`);
        toast(`Playbook "${name}" started`, 'success');
        
        // Poll for completion
        pollJobStatus(response.job_id);
      } else {
        appendLog(`[ERROR] Failed to start playbook: ${response.error || 'Unknown error'}`);
        toast('Failed to start playbook', 'error');
      }
    } catch (e) {
      appendLog(`[ERROR] ${e.message}`);
      toast('Failed to run playbook: ' + e.message, 'error');
    }
  };

  function pollJobStatus(jobId) {
    const interval = setInterval(async () => {
      try {
        const job = await jfetch(API(`api/orchestrator/status/${jobId}`));
        
        if (job.status === 'completed' || job.status === 'failed') {
          clearInterval(interval);
          appendLog(`\n[JARVIS] Job ${job.status.toUpperCase()} (Exit code: ${job.exit_code})`);
          orchLoadHistory();
        }
      } catch (e) {
        clearInterval(interval);
      }
    }, 2000);
  }

  // ============================================
  // SERVERS
  // ============================================
  window.orchLoadServers = async function() {
    const container = document.getElementById('servers-list');
    if (!container) return;
    
    try {
      container.innerHTML = '<div class="text-center text-muted">Loading servers...</div>';
      const data = await jfetch(API('api/orchestrator/servers'));
      
      if (!data.servers || data.servers.length === 0) {
        container.innerHTML = '<div class="text-center text-muted">No servers configured yet. Click "Add Server" to get started.</div>';
        return;
      }
      
      container.innerHTML = data.servers.map(s => `
        <div class="server-card">
          <div class="server-info">
            <div class="server-name">${s.name}</div>
            <div class="server-details">
              ${s.username}@${s.hostname}:${s.port} | 
              Groups: ${s.groups || 'none'} | 
              Auth: ${s.has_password ? '🔐 Password' : '🔑 Key'}
            </div>
            ${s.description ? `<div class="server-details" style="margin-top: 4px; color: var(--text-muted);">${s.description}</div>` : ''}
          </div>
          <div class="server-actions">
            <button class="btn" onclick="orchEditServer(${s.id})">✏️ Edit</button>
            <button class="btn danger" onclick="orchDeleteServer(${s.id}, '${s.name.replace(/'/g, "\\'")}')">🗑️ Delete</button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = '<div class="text-center text-muted">Failed to load servers</div>';
      toast('Failed to load servers: ' + e.message, 'error');
    }
  };

  window.orchShowAddServer = function() {
    const modal = document.getElementById('server-modal');
    if (modal) {
      modal.classList.add('active');
      document.getElementById('server-form').reset();
    }
  };

  window.orchCloseServerModal = function() {
    const modal = document.getElementById('server-modal');
    if (modal) modal.classList.remove('active');
  };

  window.orchSaveServer = async function(event) {
    event.preventDefault();
    
    const data = {
      name: document.getElementById('srv-name').value,
      hostname: document.getElementById('srv-host').value,
      port: parseInt(document.getElementById('srv-port').value),
      username: document.getElementById('srv-user').value,
      password: document.getElementById('srv-pass').value,
      groups: document.getElementById('srv-groups').value,
      description: document.getElementById('srv-desc').value
    };
    
    try {
      const btn = event.submitter;
      btn.classList.add('loading');
      
      await jfetch(API('api/orchestrator/servers'), {
        method: 'POST',
        body: JSON.stringify(data)
      });
      
      orchCloseServerModal();
      orchLoadServers();
      toast('Server added successfully', 'success');
    } catch (e) {
      toast('Failed to add server: ' + e.message, 'error');
    } finally {
      const btn = event.submitter;
      if (btn) btn.classList.remove('loading');
    }
  };

  // Edit Server Functions
  window.orchEditServer = async function(serverId) {
    const modal = document.getElementById('edit-server-modal');
    if (!modal) return;
    
    try {
      // Fetch full server details (includes password)
      const server = await jfetch(API(`api/orchestrator/servers/${serverId}`));
      
      if (!server) {
        toast('Server not found', 'error');
        return;
      }
      
      // Populate form
      document.getElementById('edit-srv-id').value = server.id;
      document.getElementById('edit-srv-name').value = server.name;
      document.getElementById('edit-srv-host').value = server.hostname;
      document.getElementById('edit-srv-port').value = server.port;
      document.getElementById('edit-srv-user').value = server.username;
      document.getElementById('edit-srv-pass').value = ''; // Don't show existing password
      document.getElementById('edit-srv-groups').value = server.groups || '';
      document.getElementById('edit-srv-desc').value = server.description || '';
      
      modal.classList.add('active');
    } catch (e) {
      toast('Failed to load server: ' + e.message, 'error');
    }
  };

  window.orchCloseEditServerModal = function() {
    const modal = document.getElementById('edit-server-modal');
    if (modal) modal.classList.remove('active');
  };

  window.orchUpdateServer = async function(event) {
    event.preventDefault();
    
    const serverId = document.getElementById('edit-srv-id').value;
    const password = document.getElementById('edit-srv-pass').value;
    
    const data = {
      name: document.getElementById('edit-srv-name').value,
      hostname: document.getElementById('edit-srv-host').value,
      port: parseInt(document.getElementById('edit-srv-port').value),
      username: document.getElementById('edit-srv-user').value,
      groups: document.getElementById('edit-srv-groups').value,
      description: document.getElementById('edit-srv-desc').value
    };
    
    // Only include password if it was changed
    if (password) {
      data.password = password;
    }
    
    try {
      const btn = event.submitter;
      btn.classList.add('loading');
      
      await jfetch(API(`api/orchestrator/servers/${serverId}`), {
        method: 'PUT',
        body: JSON.stringify(data)
      });
      
      orchCloseEditServerModal();
      orchLoadServers();
      toast('Server updated successfully', 'success');
    } catch (e) {
      toast('Failed to update server: ' + e.message, 'error');
    } finally {
      const btn = event.submitter;
      if (btn) btn.classList.remove('loading');
    }
  };

  window.orchDeleteServer = async function(serverId, serverName) {
    if (!confirm(`Delete server "${serverName}"?`)) return;
    
    try {
      await jfetch(API(`api/orchestrator/servers/${serverId}`), {
        method: 'DELETE'
      });
      
      orchLoadServers();
      toast('Server deleted', 'success');
    } catch (e) {
      toast('Failed to delete server: ' + e.message, 'error');
    }
  };

  // ============================================
  // SCHEDULES
  // ============================================
  window.orchLoadSchedules = async function() {
    const tbody = document.getElementById('schedules-list');
    if (!tbody) return;
    
    try {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading schedules...</td></tr>';
      const data = await jfetch(API('api/orchestrator/schedules'));
      
      if (!data.schedules || data.schedules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No schedules configured. Click "Add Schedule" to create one.</td></tr>';
        return;
      }
      
      tbody.innerHTML = data.schedules.map(s => `
        <tr>
          <td>${s.playbook}</td>
          <td><code style="background: var(--surface-tertiary); padding: 2px 6px; border-radius: 4px;">${s.cron}</code></td>
          <td>${s.inventory_group || 'all'}</td>
          <td>${s.last_run ? new Date(s.last_run).toLocaleString() : 'Never'}</td>
          <td>${s.next_run ? new Date(s.next_run).toLocaleString() : '—'}</td>
          <td>
            <span class="status-badge ${s.enabled ? 'completed' : 'disabled'}">${s.enabled ? 'Enabled' : 'Disabled'}</span>
            ${s.notify_on_completion ? '' : '<span class="status-badge disabled" style="margin-left: 4px;">🔕</span>'}
          </td>
          <td>
            <button class="btn" onclick="orchEditSchedule(${s.id})">✏️ Edit</button>
            <button class="btn" onclick="orchToggleSchedule(${s.id}, ${s.enabled})">${s.enabled ? 'Disable' : 'Enable'}</button>
            <button class="btn danger" onclick="orchDeleteSchedule(${s.id}, '${s.playbook.replace(/'/g, "\\'")}')">Delete</button>
          </td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Failed to load schedules</td></tr>';
      toast('Failed to load schedules: ' + e.message, 'error');
    }
  };

  window.orchShowAddSchedule = async function() {
    const modal = document.getElementById('schedule-modal');
    if (!modal) return;
    
    // Reset editing mode
    editingScheduleId = null;
    const modalTitle = modal.querySelector('h2');
    if (modalTitle) modalTitle.textContent = 'Create Schedule';
    
    // Populate playbook dropdown with organized playbooks
    try {
      const data = await jfetch(API('api/orchestrator/playbooks/organized'));
      const select = document.getElementById('sched-playbook');
      
      if (select && data.playbooks) {
        let options = '<option value="">Select a playbook...</option>';
        
        for (const [category, playbooks] of Object.entries(data.playbooks).sort()) {
          const categoryName = category === 'root' ? 'Root' : category.charAt(0).toUpperCase() + category.slice(1);
          options += `<optgroup label="${categoryName}">`;
          playbooks.forEach(p => {
            options += `<option value="${p.path}">${p.name}</option>`;
          });
          options += '</optgroup>';
        }
        
        select.innerHTML = options;
      }
      
      modal.classList.add('active');
      document.getElementById('schedule-form').reset();
      document.getElementById('sched-notify').checked = true; // Default to notifications enabled
    } catch (e) {
      toast('Failed to load playbooks: ' + e.message, 'error');
    }
  };

  window.orchEditSchedule = async function(scheduleId) {
    const modal = document.getElementById('schedule-modal');
    if (!modal) return;
    
    try {
      // Set editing mode
      editingScheduleId = scheduleId;
      const modalTitle = modal.querySelector('h2');
      if (modalTitle) modalTitle.textContent = 'Edit Schedule';
      
      // Fetch schedule details
      const schedule = await jfetch(API(`api/orchestrator/schedules/${scheduleId}`));
      
      if (!schedule) {
        toast('Schedule not found', 'error');
        return;
      }
      
      // Load playbooks into dropdown
      const playbooksData = await jfetch(API('api/orchestrator/playbooks/organized'));
      const select = document.getElementById('sched-playbook');
      
      if (select && playbooksData.playbooks) {
        let options = '<option value="">Select a playbook...</option>';
        for (const [category, playbooks] of Object.entries(playbooksData.playbooks).sort()) {
          const categoryName = category === 'root' ? 'Root' : category.charAt(0).toUpperCase() + category.slice(1);
          options += `<optgroup label="${categoryName}">`;
          playbooks.forEach(p => {
            options += `<option value="${p.path}">${p.name}</option>`;
          });
          options += '</optgroup>';
        }
        select.innerHTML = options;
      }
      
      // Populate form with schedule data
      document.getElementById('sched-playbook').value = schedule.playbook;
      document.getElementById('sched-group').value = schedule.inventory_group || '';
      document.getElementById('sched-cron').value = schedule.cron;
      document.getElementById('sched-notify').checked = schedule.notify_on_completion !== 0;
      
      modal.classList.add('active');
    } catch (e) {
      toast('Failed to load schedule: ' + e.message, 'error');
    }
  };

  window.orchCloseScheduleModal = function() {
    const modal = document.getElementById('schedule-modal');
    if (modal) modal.classList.remove('active');
    editingScheduleId = null;
  };

  window.orchApplyPreset = function() {
    const preset = document.getElementById('sched-preset').value;
    const cronInput = document.getElementById('sched-cron');
    if (preset && cronInput) {
      cronInput.value = preset;
    }
  };

  window.orchSaveSchedule = async function(event) {
    event.preventDefault();
    
    const data = {
      name: document.getElementById('sched-playbook').value.split('/').pop(),
      playbook: document.getElementById('sched-playbook').value,
      cron: document.getElementById('sched-cron').value,
      inventory_group: document.getElementById('sched-group').value || null,
      notify_on_completion: document.getElementById('sched-notify').checked,
      enabled: true
    };
    
    try {
      const btn = event.submitter;
      btn.classList.add('loading');
      
      if (editingScheduleId) {
        // Update existing schedule
        await jfetch(API(`api/orchestrator/schedules/${editingScheduleId}`), {
          method: 'PUT',
          body: JSON.stringify(data)
        });
        toast('Schedule updated successfully', 'success');
      } else {
        // Create new schedule
        await jfetch(API('api/orchestrator/schedules'), {
          method: 'POST',
          body: JSON.stringify(data)
        });
        toast('Schedule created successfully', 'success');
      }
      
      orchCloseScheduleModal();
      orchLoadSchedules();
    } catch (e) {
      toast('Failed to save schedule: ' + e.message, 'error');
    } finally {
      const btn = event.submitter;
      if (btn) btn.classList.remove('loading');
    }
  };

  window.orchToggleSchedule = async function(scheduleId, currentlyEnabled) {
    try {
      await jfetch(API(`api/orchestrator/schedules/${scheduleId}`), {
        method: 'PUT',
        body: JSON.stringify({ enabled: !currentlyEnabled })
      });
      
      orchLoadSchedules();
      toast(`Schedule ${!currentlyEnabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (e) {
      toast('Failed to toggle schedule: ' + e.message, 'error');
    }
  };

  window.orchDeleteSchedule = async function(scheduleId, playbookName) {
    if (!confirm(`Delete schedule for "${playbookName}"?`)) return;
    
    try {
      await jfetch(API(`api/orchestrator/schedules/${scheduleId}`), {
        method: 'DELETE'
      });
      
      orchLoadSchedules();
      toast('Schedule deleted', 'success');
    } catch (e) {
      toast('Failed to delete schedule: ' + e.message, 'error');
    }
  };

  // ============================================
  // HISTORY
  // ============================================
  window.orchLoadHistory = async function() {
    const tbody = document.getElementById('history-list');
    if (!tbody) return;
    
    try {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Loading history...</td></tr>';
      const data = await jfetch(API('api/orchestrator/history?limit=20'));
      
      if (!data.jobs || data.jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No job history yet</td></tr>';
        return;
      }
      
      tbody.innerHTML = data.jobs.map(j => `
        <tr>
          <td>${j.playbook}</td>
          <td><span class="status-badge ${j.status}">${j.status.toUpperCase()}</span></td>
          <td>${new Date(j.started_at).toLocaleString()}</td>
          <td>${j.completed_at ? new Date(j.completed_at).toLocaleString() : '—'}</td>
          <td>${j.exit_code !== null ? j.exit_code : '—'}</td>
          <td>${j.triggered_by}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Failed to load history</td></tr>';
      toast('Failed to load history: ' + e.message, 'error');
    }
  };

  // ============================================
  // HISTORY MANAGEMENT
  // ============================================
  window.orchShowHistorySettings = async function() {
    const modal = document.getElementById('history-modal');
    if (!modal) return;
    
    // Load history stats
    try {
      const stats = await jfetch(API('api/orchestrator/history/stats'));
      document.getElementById('history-total').textContent = stats.total_entries || 0;
    } catch (e) {
      console.error('Failed to load history stats:', e);
    }
    
    modal.classList.add('active');
  };

  window.orchCloseHistoryModal = function() {
    const modal = document.getElementById('history-modal');
    if (modal) modal.classList.remove('active');
  };

  window.orchPurgeHistory = async function(criteria) {
    let confirmMsg = '';
    
    switch(criteria) {
      case 'all':
        confirmMsg = '⚠️ DELETE ALL HISTORY?\n\nThis will permanently delete all execution history and cannot be undone.\n\nAre you absolutely sure?';
        break;
      case 'failed':
        confirmMsg = 'Delete all failed job executions?';
        break;
      case 'completed':
        confirmMsg = 'Delete all successful job executions?';
        break;
      case 'older_than_30':
        confirmMsg = 'Delete all history older than 30 days?';
        break;
      case 'older_than_90':
        confirmMsg = 'Delete all history older than 90 days?';
        break;
    }
    
    if (!confirm(confirmMsg)) return;
    
    try {
      const result = await jfetch(API('api/orchestrator/history/purge'), {
        method: 'POST',
        body: JSON.stringify({ criteria })
      });
      
      toast(`Deleted ${result.deleted} entries`, 'success');
      orchLoadHistory();
      
      if (criteria === 'all') {
        orchCloseHistoryModal();
      } else {
        // Reload stats
        orchShowHistorySettings();
      }
    } catch (e) {
      toast('Failed to purge history: ' + e.message, 'error');
    }
  };

  // ============================================
  // INITIALIZATION
  // ============================================
  function initOrchestrator() {
    // Connect WebSocket for live logs
    connectWebSocket();
    
    // Load initial data
    orchLoadPlaybooks();
    
    console.log('[Orchestrator] Frontend initialized');
  }

  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOrchestrator);
  } else {
    initOrchestrator();
  }
})();