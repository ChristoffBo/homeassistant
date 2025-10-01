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
    app.router.add_post("/api/orchestrator/run/{playbook:.*}", api_run_playbook)
    app.router.add_get("/api/orchestrator/status/{id:\\d+}", api_get_status)
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