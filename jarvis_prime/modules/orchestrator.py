#!/usr/bin/env python3
# /app/orchestrator.py
#
# Orchestrator: Lightweight automation module for Jarvis Prime
# Runs playbooks/scripts, manages servers, logs results, notifies on completion

import os
import json
import sqlite3
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template
from flask_socketio import emit

# Create blueprint
orchestrator_bp = Blueprint("orchestrator", __name__, url_prefix="/orchestrator")

class Orchestrator:
    def __init__(self, config, db_path, socketio=None, notify_callback=None, logger=None):
        self.config = config
        self.db_path = db_path
        self.socketio = socketio
        self.notify_callback = notify_callback
        self.logger = logger or print
        self.playbooks_path = config.get("playbooks_path", "/share/jarvis_prime/playbooks")
        self.runner = config.get("runner", "script")
        self.init_db()

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
            conn.commit()

    def list_playbooks(self):
        """List all available playbooks from the playbooks directory"""
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

    def get_job_history(self, limit=50):
        """Get recent job execution history"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orchestration_jobs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

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

        thread = threading.Thread(target=self._execute_playbook, args=(job_id, playbook_name, inventory_group))
        thread.daemon = True
        thread.start()

        return job_id

    def _execute_playbook(self, job_id, playbook_name, inventory_group=None):
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
                
                # Add Ansible config to accept host keys and use passwords
                cmd = [
                    "ansible-playbook",
                    "-i", str(inventory_path),
                    str(playbook_path)
                ]
                
                # Set environment variables for Ansible
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

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

            # Store PID
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE orchestration_jobs SET pid = ? WHERE id = ?", (process.pid, job_id))
                conn.commit()

            output_lines = []
            for line in iter(process.stdout.readline, ""):
                if line:
                    line = line.rstrip()
                    output_lines.append(line)
                    if self.socketio:
                        try:
                            self.socketio.emit("orchestration_log", {"job_id": job_id, "line": line}, namespace="/jarvis")
                        except Exception:
                            pass  # Don't let WebSocket errors kill the job

            process.wait()
            exit_code = process.returncode
            output = "\n".join(output_lines)

            status = "completed" if exit_code == 0 else "failed"
            self._update_job(job_id, status, output, exit_code, process.pid)
            self._send_notification(job_id, playbook_name, status, exit_code)

            # Cleanup temporary inventory file
            if ext in [".yml", ".yaml"] and self.runner == "ansible":
                try:
                    inventory_path.unlink()
                except Exception:
                    pass

        except Exception as e:
            msg = f"Execution error: {e}"
            self._update_job(job_id, "failed", msg, -1, None)
            self._send_notification(job_id, playbook_name, "failed", -1, msg)

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

    def _send_notification(self, job_id, playbook_name, status, exit_code, error=None):
        """Send notification via existing notify system"""
        if not self.notify_callback:
            return

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

def init_orchestrator(config, db_path, socketio=None, notify_callback=None, logger=None):
    """Initialize the orchestrator module"""
    global orchestrator
    orchestrator = Orchestrator(config, db_path, socketio, notify_callback, logger)
    return orchestrator

# Flask routes
@orchestrator_bp.route("/list", methods=["GET"])
def list_playbooks():
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    return jsonify({"playbooks": orchestrator.list_playbooks()})

@orchestrator_bp.route("/run/<playbook>", methods=["POST"])
def run_playbook(playbook):
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    data = request.json or {}
    triggered_by = data.get("triggered_by", "manual")
    inventory_group = data.get("inventory_group")
    try:
        job_id = orchestrator.run_playbook(playbook, triggered_by, inventory_group)
        return jsonify({"success": True, "job_id": job_id, "message": f"Playbook {playbook} started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@orchestrator_bp.route("/status/<int:job_id>", methods=["GET"])
def get_status(job_id):
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    job = orchestrator.get_job_status(job_id)
    return jsonify(job) if job else (jsonify({"error": "Job not found"}), 404)

@orchestrator_bp.route("/history", methods=["GET"])
def history():
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"jobs": orchestrator.get_job_history(limit)})

@orchestrator_bp.route("/servers", methods=["GET"])
def list_servers():
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    group = request.args.get("group")
    return jsonify({"servers": orchestrator.list_servers(group)})

@orchestrator_bp.route("/servers", methods=["POST"])
def add_server():
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    data = request.json
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
        return jsonify({"success": True, "server_id": server_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@orchestrator_bp.route("/servers/<int:server_id>", methods=["PUT"])
def update_server(server_id):
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    data = request.json
    try:
        success = orchestrator.update_server(server_id, **data)
        if success:
            return jsonify({"success": True})
        return jsonify({"error": "Server not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@orchestrator_bp.route("/servers/<int:server_id>", methods=["DELETE"])
def delete_server(server_id):
    if not orchestrator:
        return jsonify({"error": "Orchestrator not initialized"}), 500
    try:
        success = orchestrator.delete_server(server_id)
        if success:
            return jsonify({"success": True})
        return jsonify({"error": "Server not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@orchestrator_bp.route("/ui", methods=["GET"])
def ui():
    return render_template("orchestration.html")