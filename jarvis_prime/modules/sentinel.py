#!/usr/bin/env python3
# /app/sentinel.py
# UPGRADED: Added Analytics auto-heal integration with preset templates
# FIXED: SSH operations run in thread pool to prevent blocking Jarvis event loop

import os
import json
import sqlite3
import asyncio
import paramiko
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import web
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def ensure_sentinel_defaults(base="/share/jarvis_prime/sentinel"):
    os.makedirs(base, exist_ok=True)
    defaults = {
        "settings.json": {
            "check_interval": 300,
            "notify_on_failure": True,
            "notify_recovery": True,
            "auto_reload_templates": True,
            "github_templates_url": "",
            "auto_heal_mode": "explicit"  # NEW: off, explicit, or auto
        },
        "servers.json": [],
        "templates.json": [],
        "monitoring.json": [],
        "maintenance.json": [],
        "quiet_hours.json": {
            "enabled": False,
            "start": "22:00",
            "end": "08:00"
        }
    }
    for name, content in defaults.items():
        path = os.path.join(base, name)
        if not os.path.exists(path) or os.path.getsize(path) < 10:
            with open(path, "w") as f:
                json.dump(content, f, indent=2)


ensure_sentinel_defaults()


class Sentinel:
    def __init__(self, config, db_path, notify_callback=None, logger_func=None):
        self.config = config
        self.db_path = db_path
        self.notify_callback = notify_callback
        self.logger = logger_func or print
        self.data_path = config.get("data_path", "/share/jarvis_prime/sentinel")
        self.templates_path = os.path.join(os.path.dirname(__file__), "sentinel_templates")
        self.custom_templates_path = os.path.join(self.data_path, "custom_templates")
        self._monitor_tasks = {}
        self._service_states = {}
        self._failure_counts = {}
        self._log_listeners = {}
        
        # Thread pool for blocking SSH operations
        self._ssh_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sentinel_ssh")
        
        # NEW: Auto-heal templates storage
        self.heal_templates_path = os.path.join(self.data_path, "heal_templates.json")
        self.heal_presets_path = "/app/sentinel_heal_presets.json"
        self.check_presets_path = "/app/sentinel_check_presets.json"
        self.custom_presets_path = os.path.join(self.data_path, "custom_presets.json")
        
        self.init_storage()
        self.init_db()
        self.init_presets()

    def init_storage(self):
        """Initialize storage directories and files"""
        os.makedirs(self.data_path, exist_ok=True)
        os.makedirs(self.custom_templates_path, exist_ok=True)
        os.makedirs(self.templates_path, exist_ok=True)
        
        for filename in ["servers.json", "monitoring.json", "maintenance_windows.json", "quiet_hours.json", "settings.json"]:
            filepath = os.path.join(self.data_path, filename)
            if not os.path.exists(filepath):
                default = {"github_templates_url": "", "auto_heal_mode": "explicit"} if filename == "settings.json" else []
                with open(filepath, "w") as f:
                    json.dump(default, f)
        
        # Initialize heal templates file
        if not os.path.exists(self.heal_templates_path):
            with open(self.heal_templates_path, "w") as f:
                json.dump([], f)

    def init_presets(self):
        """Initialize default preset files"""
        # Default heal presets
        if not os.path.exists(self.heal_presets_path):
            default_heal = [
                {"label": "Restart Docker Container", "cmd": "docker restart {name}"},
                {"label": "Restart Systemd Service", "cmd": "systemctl restart {name}"},
                {"label": "Recreate Container", "cmd": "docker rm -f {name} && docker-compose up -d {name}"},
                {"label": "Wake Host via MAC", "cmd": "wakeonlan {mac}"},
                {"label": "Reboot Host", "cmd": "reboot"},
                {"label": "Restart Docker Engine", "cmd": "systemctl restart docker"},
                {"label": "Restart SSH Service", "cmd": "systemctl restart ssh"},
                {"label": "Restart Plex", "cmd": "docker restart plex"},
                {"label": "Restart Transmission", "cmd": "systemctl restart transmission-daemon"}
            ]
            with open(self.heal_presets_path, "w") as f:
                json.dump(default_heal, f, indent=2)
        
        # Default check presets
        if not os.path.exists(self.check_presets_path):
            default_check = [
                {"label": "Check Docker Container", "check_command": "docker inspect -f '{{.State.Running}}' {name}", "expected_output": "true"},
                {"label": "Check HDD SMART Health", "check_command": "smartctl -H /dev/{device}", "expected_output": "PASSED"},
                {"label": "Check Disk Usage", "check_command": "df -h | grep {mount}", "expected_output": ""},
                {"label": "Check Systemd Service", "check_command": "systemctl is-active {name}", "expected_output": "active"},
                {"label": "Check Ping", "check_command": "ping -c1 {host}", "expected_output": "0"},
                {"label": "Check CPU Load", "check_command": "uptime | awk -F'load average:' '{print $2}'", "expected_output": ""}
            ]
            with open(self.check_presets_path, "w") as f:
                json.dump(default_check, f, indent=2)
        
        # Custom presets (user overrides)
        if not os.path.exists(self.custom_presets_path):
            with open(self.custom_presets_path, "w") as f:
                json.dump({"heal": [], "check": []}, f, indent=2)

    def load_presets(self):
        """Load all presets (defaults + custom) with priority"""
        result = {"heal": [], "check": []}
        
        try:
            # Load custom first (highest priority)
            if os.path.exists(self.custom_presets_path):
                with open(self.custom_presets_path, "r") as f:
                    custom = json.load(f)
                    result["heal"].extend(custom.get("heal", []))
                    result["check"].extend(custom.get("check", []))
            
            # Load defaults
            if os.path.exists(self.heal_presets_path):
                with open(self.heal_presets_path, "r") as f:
                    result["heal"].extend(json.load(f))
            
            if os.path.exists(self.check_presets_path):
                with open(self.check_presets_path, "r") as f:
                    result["check"].extend(json.load(f))
        except Exception as e:
            logger.error(f"Error loading presets: {e}")
        
        return result

    def load_heal_templates(self):
        """Load auto-heal templates"""
        try:
            with open(self.heal_templates_path, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def save_heal_templates(self, templates):
        """Save auto-heal templates"""
        try:
            with open(self.heal_templates_path, "w") as f:
                json.dump(templates, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving heal templates: {e}")
            return False

    def get_heal_template(self, service_name):
        """Get heal template for a specific service"""
        templates = self.load_heal_templates()
        for t in templates:
            if t.get("service_name") == service_name and t.get("enabled"):
                return t
        return None

    def load_settings(self):
        """Load Sentinel settings including auto_heal_mode"""
        filepath = os.path.join(self.data_path, "settings.json")
        try:
            with open(filepath, "r") as f:
                settings = json.load(f)
                # Ensure auto_heal_mode exists
                if "auto_heal_mode" not in settings:
                    settings["auto_heal_mode"] = "explicit"
                return settings
        except Exception:
            return {"github_templates_url": "", "auto_heal_mode": "explicit"}

    def save_settings(self, settings):
        """Save Sentinel settings"""
        filepath = os.path.join(self.data_path, "settings.json")
        try:
            with open(filepath, "w") as f:
                json.dump(settings, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving settings: {e}")
            return False

    def init_db(self):
        """Initialize Sentinel database tables"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Existing tables...
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL,
                server_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                successful INTEGER DEFAULT 0
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_stats (
                server_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                total_checks INTEGER DEFAULT 0,
                successful_checks INTEGER DEFAULT 0,
                failed_checks INTEGER DEFAULT 0,
                total_repairs INTEGER DEFAULT 0,
                successful_repairs INTEGER DEFAULT 0,
                failed_repairs INTEGER DEFAULT 0,
                last_check INTEGER,
                last_success INTEGER,
                last_failure INTEGER,
                PRIMARY KEY (server_id, service_id)
            )
        """)
        
        # NEW: Auto-heal execution log
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_heal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                trigger_source TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                success INTEGER DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                final_status TEXT,
                commands_run TEXT,
                error_message TEXT
            )
        """)
        
        conn.commit()
        conn.close()

    # NEW: Analytics trigger endpoint
    async def api_analytics_trigger(self, request):
        """
        Receives failure notifications from Analytics
        Triggers auto-heal if template exists and is enabled
        """
        try:
            data = await request.json()
            service_name = data.get("service")
            host = data.get("host")
            status = data.get("status")
            
            if not service_name or status != "down":
                return web.json_response({"error": "Invalid trigger data"}, status=400)
            
            # Check auto_heal_mode setting
            settings = self.load_settings()
            heal_mode = settings.get("auto_heal_mode", "explicit")
            
            if heal_mode == "off":
                return web.json_response({"status": "disabled", "message": "Auto-heal is disabled"})
            
            # Find matching heal template
            template = self.get_heal_template(service_name)
            
            if not template:
                return web.json_response({
                    "status": "no_template",
                    "message": f"No enabled heal template found for {service_name}"
                })
            
            # Generate execution ID
            execution_id = f"analytics_{service_name}_{int(datetime.now().timestamp())}"
            
            # Execute heal in background
            asyncio.create_task(self._execute_heal(
                template=template,
                execution_id=execution_id,
                trigger_source="analytics",
                host=host
            ))
            
            return web.json_response({
                "status": "triggered",
                "execution_id": execution_id,
                "service": service_name
            })
            
        except Exception as e:
            logger.error(f"Analytics trigger error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _execute_heal(self, template, execution_id, trigger_source, host=None):
        """
        Execute heal commands for a service
        Includes verification, retry logic, and feedback to Analytics
        """
        service_name = template["service_name"]
        heal_commands = template.get("heal_commands", [])
        check_command = template.get("check_command")
        verify_command = template.get("verify_command")
        expected_output = template.get("expected_output", "")
        retry_count = template.get("retry_count", 3)
        retry_delay = template.get("retry_delay", 10)
        server_id = template.get("server_id")
        
        log_entry = {
            "execution_id": execution_id,
            "service_name": service_name,
            "trigger_source": trigger_source,
            "timestamp": int(datetime.now().timestamp()),
            "success": 0,
            "attempts": 0,
            "commands_run": [],
            "error_message": None
        }
        
        try:
            # Find server config
            servers = self.load_servers()
            server = next((s for s in servers if s["id"] == server_id), None)
            
            if not server:
                log_entry["error_message"] = "Server not found"
                self._save_heal_log(log_entry)
                return
            
            # STEP 1: Verify service is actually down
            if check_command:
                self._log(execution_id, "info", f"Verifying {service_name} status...")
                check_result = await self._run_ssh_command(server, check_command)
                
                if self._check_success(check_result, expected_output):
                    self._log(execution_id, "info", f"{service_name} is actually UP - skipping heal")
                    log_entry["final_status"] = "already_up"
                    self._save_heal_log(log_entry)
                    return
            
            # STEP 2: Run heal commands
            for attempt in range(1, retry_count + 1):
                log_entry["attempts"] = attempt
                self._log(execution_id, "info", f"Heal attempt {attempt}/{retry_count} for {service_name}")
                
                for cmd in heal_commands:
                    # Replace placeholders
                    cmd_formatted = self._format_command(cmd, template)
                    log_entry["commands_run"].append(cmd_formatted)
                    
                    self._log(execution_id, "info", f"Running: {cmd_formatted}")
                    result = await self._run_ssh_command(server, cmd_formatted)
                    
                    if result.get("returncode") != 0:
                        self._log(execution_id, "warning", f"Command failed: {result.get('stderr', 'Unknown error')}")
                
                # Wait before verification
                await asyncio.sleep(retry_delay)
                
                # STEP 3: Verify success
                if verify_command:
                    self._log(execution_id, "info", f"Verifying {service_name} recovery...")
                    verify_result = await self._run_ssh_command(server, verify_command)
                    
                    if self._check_success(verify_result, expected_output):
                        self._log(execution_id, "success", f"✅ {service_name} recovered successfully")
                        log_entry["success"] = 1
                        log_entry["final_status"] = "up"
                        
                        # Notify Analytics
                        await self._notify_analytics(service_name, "up", "sentinel")
                        
                        # Notify Jarvis
                        if self.notify_callback:
                            await self.notify_callback({
                                "title": f"✅ {service_name} Recovered",
                                "message": f"{service_name} automatically healed by Sentinel (attempt {attempt}/{retry_count})",
                                "priority": "normal"
                            })
                        
                        self._save_heal_log(log_entry)
                        return
            
            # All attempts failed
            self._log(execution_id, "error", f"🚨 {service_name} failed to recover after {retry_count} attempts")
            log_entry["final_status"] = "down"
            log_entry["error_message"] = "Max retries exhausted"
            
            # Notify Jarvis of failure
            if self.notify_callback:
                await self.notify_callback({
                    "title": f"🚨 {service_name} Auto-Heal Failed",
                    "message": f"{service_name} still down after {retry_count} heal attempts - manual intervention required",
                    "priority": "high"
                })
            
        except Exception as e:
            log_entry["error_message"] = str(e)
            self._log(execution_id, "error", f"Heal execution error: {e}")
        
        self._save_heal_log(log_entry)

    def _format_command(self, cmd, template):
        """Replace placeholders in commands with actual values"""
        replacements = {
            "{name}": template.get("service_name", ""),
            "{image}": template.get("docker_image", ""),
            "{mac}": template.get("mac_address", ""),
            "{device}": template.get("device", ""),
            "{mount}": template.get("mount_point", ""),
            "{host}": template.get("host", "")
        }
        
        for placeholder, value in replacements.items():
            cmd = cmd.replace(placeholder, value)
        
        return cmd

    def _check_success(self, result, expected_output):
        """Check if command output matches expected result"""
        if result.get("returncode") != 0:
            return False
        
        if not expected_output:
            return True
        
        output = result.get("stdout", "").strip()
        return expected_output.lower() in output.lower()

    async def _notify_analytics(self, service_name, status, resolved_by):
        """Send status update back to Analytics"""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post("http://localhost:2580/api/analytics/update", json={
                    "service": service_name,
                    "status": status,
                    "resolved_by": resolved_by
                })
        except Exception as e:
            logger.error(f"Failed to notify Analytics: {e}")

    def _save_heal_log(self, log_entry):
        """Save heal execution to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO sentinel_heal_log 
                (execution_id, service_name, trigger_source, timestamp, success, attempts, final_status, commands_run, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_entry["execution_id"],
                log_entry["service_name"],
                log_entry["trigger_source"],
                log_entry["timestamp"],
                log_entry["success"],
                log_entry["attempts"],
                log_entry.get("final_status"),
                json.dumps(log_entry.get("commands_run", [])),
                log_entry.get("error_message")
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving heal log: {e}")

    def _log(self, execution_id, level, message):
        """Log message and emit to listeners"""
        timestamp = int(datetime.now().timestamp())
        
        # Emit to WebSocket listeners
        if execution_id in self._log_listeners:
            for listener in self._log_listeners[execution_id]:
                try:
                    asyncio.create_task(listener.send_json({
                        "timestamp": timestamp,
                        "level": level,
                        "message": message
                    }))
                except:
                    pass
        
        logger.info(f"[{execution_id}] {level.upper()}: {message}")

    async def _run_ssh_command(self, server, command):
        """Execute SSH command in thread pool (non-blocking)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._ssh_executor,
            self._ssh_command_sync,
            server,
            command
        )

    def _ssh_command_sync(self, server, command):
        """Synchronous SSH command execution"""
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            client.connect(
                hostname=server["host"],
                port=server.get("port", 22),
                username=server["username"],
                password=server.get("password"),
                key_filename=server.get("ssh_key")
            )
            
            stdin, stdout, stderr = client.exec_command(command)
            
            result = {
                "returncode": stdout.channel.recv_exit_status(),
                "stdout": stdout.read().decode("utf-8", errors="ignore"),
                "stderr": stderr.read().decode("utf-8", errors="ignore")
            }
            
            client.close()
            return result
            
        except Exception as e:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": str(e)
            }

    # API: Heal Templates Management
    async def api_get_heal_templates(self, request):
        """Get all auto-heal templates"""
        templates = self.load_heal_templates()
        return web.json_response({"templates": templates})

    async def api_add_heal_template(self, request):
        """Add new auto-heal template"""
        try:
            data = await request.json()
            templates = self.load_heal_templates()
            
            # Generate ID if not provided
            if "id" not in data:
                data["id"] = f"heal_{data['service_name']}_{int(datetime.now().timestamp())}"
            
            templates.append(data)
            self.save_heal_templates(templates)
            
            return web.json_response({"success": True, "template": data})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def api_update_heal_template(self, request):
        """Update existing heal template"""
        try:
            template_id = request.match_info["template_id"]
            data = await request.json()
            templates = self.load_heal_templates()
            
            for i, t in enumerate(templates):
                if t["id"] == template_id:
                    templates[i] = {**t, **data}
                    self.save_heal_templates(templates)
                    return web.json_response({"success": True, "template": templates[i]})
            
            return web.json_response({"error": "Template not found"}, status=404)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def api_delete_heal_template(self, request):
        """Delete heal template"""
        try:
            template_id = request.match_info["template_id"]
            templates = self.load_heal_templates()
            templates = [t for t in templates if t["id"] != template_id]
            self.save_heal_templates(templates)
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def api_get_presets(self, request):
        """Get all heal and check presets"""
        presets = self.load_presets()
        return web.json_response(presets)

    async def api_add_custom_preset(self, request):
        """Add custom preset"""
        try:
            data = await request.json()
            preset_type = data.get("type")  # "heal" or "check"
            preset_data = data.get("preset")
            
            if preset_type not in ["heal", "check"]:
                return web.json_response({"error": "Invalid type"}, status=400)
            
            custom = {}
            if os.path.exists(self.custom_presets_path):
                with open(self.custom_presets_path, "r") as f:
                    custom = json.load(f)
            
            if preset_type not in custom:
                custom[preset_type] = []
            
            custom[preset_type].append(preset_data)
            
            with open(self.custom_presets_path, "w") as f:
                json.dump(custom, f, indent=2)
            
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def api_get_heal_history(self, request):
        """Get auto-heal execution history"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            
            limit = int(request.query.get("limit", 50))
            service = request.query.get("service")
            
            query = "SELECT * FROM sentinel_heal_log"
            params = []
            
            if service:
                query += " WHERE service_name = ?"
                params.append(service)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cur.execute(query, params)
            history = [dict(row) for row in cur.fetchall()]
            
            # Parse JSON fields
            for h in history:
                if h.get("commands_run"):
                    h["commands_run"] = json.loads(h["commands_run"])
            
            conn.close()
            return web.json_response({"history": history})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # EXISTING SENTINEL METHODS (keeping all original functionality)
    # [All your existing methods remain unchanged]
    
    def load_servers(self):
        """Load server configurations"""
        filepath = os.path.join(self.data_path, "servers.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def save_servers(self, servers):
        """Save server configurations"""
        filepath = os.path.join(self.data_path, "servers.json")
        try:
            with open(filepath, "w") as f:
                json.dump(servers, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving servers: {e}")
            return False

    def load_templates(self):
        """Load available check templates"""
        templates = []
        
        # Load from template directories
        for template_dir in [self.templates_path, self.custom_templates_path]:
            if not os.path.exists(template_dir):
                continue
            
            for filename in os.listdir(template_dir):
                if filename.endswith(".json"):
                    try:
                        with open(os.path.join(template_dir, filename), "r") as f:
                            template = json.load(f)
                            template["filename"] = filename
                            template["custom"] = (template_dir == self.custom_templates_path)
                            templates.append(template)
                    except Exception as e:
                        self.logger(f"Error loading template {filename}: {e}")
        
        return templates

    def get_template(self, template_id):
        """Get specific template by ID or filename"""
        templates = self.load_templates()
        for template in templates:
            if template.get("id") == template_id or template.get("filename") == template_id:
                return template
        return None

    def load_monitoring(self):
        """Load monitoring configurations"""
        filepath = os.path.join(self.data_path, "monitoring.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def save_monitoring(self, monitoring):
        """Save monitoring configurations"""
        filepath = os.path.join(self.data_path, "monitoring.json")
        try:
            with open(filepath, "w") as f:
                json.dump(monitoring, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving monitoring: {e}")
            return False

    def load_maintenance(self):
        """Load maintenance windows"""
        filepath = os.path.join(self.data_path, "maintenance_windows.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def save_maintenance(self, windows):
        """Save maintenance windows"""
        filepath = os.path.join(self.data_path, "maintenance_windows.json")
        try:
            with open(filepath, "w") as f:
                json.dump(windows, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving maintenance windows: {e}")
            return False

    def load_quiet_hours(self):
        """Load quiet hours configuration"""
        filepath = os.path.join(self.data_path, "quiet_hours.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {"enabled": False, "start": "22:00", "end": "08:00"}

    def save_quiet_hours(self, config):
        """Save quiet hours configuration"""
        filepath = os.path.join(self.data_path, "quiet_hours.json")
        try:
            with open(filepath, "w") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving quiet hours: {e}")
            return False

    def is_in_maintenance(self, server_id):
        """Check if server is in maintenance window"""
        windows = self.load_maintenance()
        now = datetime.now()
        
        for window in windows:
            if window.get("server_id") != server_id:
                continue
            
            if not window.get("enabled", True):
                continue
            
            start = datetime.fromisoformat(window["start_time"])
            end = datetime.fromisoformat(window["end_time"])
            
            if start <= now <= end:
                return True
        
        return False

    def is_quiet_hours(self):
        """Check if currently in quiet hours"""
        config = self.load_quiet_hours()
        
        if not config.get("enabled", False):
            return False
        
        now = datetime.now().time()
        start_time = datetime.strptime(config["start"], "%H:%M").time()
        end_time = datetime.strptime(config["end"], "%H:%M").time()
        
        if start_time < end_time:
            return start_time <= now <= end_time
        else:
            return now >= start_time or now <= end_time

    def start_monitoring(self, server_id):
        """Start monitoring a specific server"""
        if server_id in self._monitor_tasks:
            return False
        
        servers = self.load_servers()
        server = next((s for s in servers if s["id"] == server_id), None)
        
        if not server:
            return False
        
        monitoring = self.load_monitoring()
        server_monitoring = next((m for m in monitoring if m["server_id"] == server_id), None)
        
        if not server_monitoring or not server_monitoring.get("enabled", True):
            return False
        
        task = asyncio.create_task(self._monitor_loop(server, server_monitoring))
        self._monitor_tasks[server_id] = task
        return True

    def stop_monitoring(self, server_id):
        """Stop monitoring a specific server"""
        if server_id not in self._monitor_tasks:
            return False
        
        task = self._monitor_tasks[server_id]
        task.cancel()
        del self._monitor_tasks[server_id]
        return True

    def start_all_monitoring(self):
        """Start monitoring for all enabled servers"""
        monitoring = self.load_monitoring()
        for config in monitoring:
            if config.get("enabled", True):
                self.start_monitoring(config["server_id"])

    def stop_all_monitoring(self):
        """Stop all monitoring"""
        for server_id in list(self._monitor_tasks.keys()):
            self.stop_monitoring(server_id)

    async def _monitor_loop(self, server, config):
        """Main monitoring loop for a server"""
        server_id = server["id"]
        interval = config.get("check_interval", 300)
        
        while True:
            try:
                # Check if in maintenance or quiet hours
                if self.is_in_maintenance(server_id) or self.is_quiet_hours():
                    await asyncio.sleep(60)
                    continue
                
                # Run checks for each enabled service
                for service_config in config.get("services", []):
                    if not service_config.get("enabled", True):
                        continue
                    
                    await self._check_service(server, service_config)
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger(f"Monitor loop error for {server_id}: {e}")
                await asyncio.sleep(60)

    async def _check_service(self, server, service_config):
        """Check a single service"""
        server_id = server["id"]
        service_id = service_config["service_id"]
        template = self.get_template(service_id)
        
        if not template:
            return
        
        execution_id = f"check_{server_id}_{service_id}_{int(datetime.now().timestamp())}"
        
        # Run check command
        check_command = template.get("check_command")
        if not check_command:
            return
        
        result = await self._run_ssh_command(server, check_command)
        expected = template.get("expected_output", "")
        success = self._check_success(result, expected)
        
        # Update stats
        self._update_stats(server_id, service_id, success, check=True)
        
        # Track state changes
        prev_state = self._service_states.get(f"{server_id}_{service_id}")
        current_state = "up" if success else "down"
        self._service_states[f"{server_id}_{service_id}"] = current_state
        
        # Handle failures
        if not success:
            self._failure_counts[f"{server_id}_{service_id}"] = self._failure_counts.get(f"{server_id}_{service_id}", 0) + 1
            
            # Auto-repair if configured
            if service_config.get("auto_repair", False):
                repair_command = template.get("repair_command")
                if repair_command:
                    await self.repair_service(server, template, execution_id)
        else:
            self._failure_counts[f"{server_id}_{service_id}"] = 0
            
            # Notify recovery
            if prev_state == "down":
                settings = self.load_settings()
                if settings.get("notify_recovery", True) and self.notify_callback:
                    await self.notify_callback({
                        "title": f"✅ {template.get('name', service_id)} Recovered",
                        "message": f"Service on {server.get('name', server_id)} is now responding normally",
                        "priority": "normal"
                    })
        
        # Notify failure
        if not success and prev_state != "down":
            settings = self.load_settings()
            if settings.get("notify_on_failure", True) and self.notify_callback:
                await self.notify_callback({
                    "title": f"🚨 {template.get('name', service_id)} Failed",
                    "message": f"Service check failed on {server.get('name', server_id)}",
                    "priority": "high"
                })

    async def repair_service(self, server, template, execution_id, manual=False):
        """Execute repair commands for a service"""
        repair_command = template.get("repair_command")
        if not repair_command:
            return
        
        server_id = server["id"]
        service_id = template.get("id", template.get("filename"))
        
        self._log(execution_id, "info", f"Starting repair for {template.get('name', service_id)}")
        
        result = await self._run_ssh_command(server, repair_command)
        success = result.get("returncode") == 0
        
        # Log result
        self._log(execution_id, "success" if success else "error", 
                 "Repair completed successfully" if success else f"Repair failed: {result.get('stderr', 'Unknown error')}")
        
        # Update stats
        self._update_stats(server_id, service_id, success, repair=True)
        
        # Save log to database
        self._save_execution_log(execution_id, server_id, service_id, success, manual)

    def _update_stats(self, server_id, service_id, success, check=False, repair=False):
        """Update service statistics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        timestamp = int(datetime.now().timestamp())
        
        cur.execute("""
            INSERT INTO sentinel_stats (server_id, service_id, total_checks, successful_checks, failed_checks, 
                                       total_repairs, successful_repairs, failed_repairs, last_check, last_success, last_failure)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id, service_id) DO UPDATE SET
                total_checks = total_checks + ?,
                successful_checks = successful_checks + ?,
                failed_checks = failed_checks + ?,
                total_repairs = total_repairs + ?,
                successful_repairs = successful_repairs + ?,
                failed_repairs = failed_repairs + ?,
                last_check = ?,
                last_success = CASE WHEN ? THEN ? ELSE last_success END,
                last_failure = CASE WHEN NOT ? THEN ? ELSE last_failure END
        """, (
            server_id, service_id,
            1 if check else 0, 1 if (check and success) else 0, 1 if (check and not success) else 0,
            1 if repair else 0, 1 if (repair and success) else 0, 1 if (repair and not success) else 0,
            timestamp if check else None,
            timestamp if success else None,
            timestamp if not success else None,
            # UPDATE clause
            1 if check else 0,
            1 if (check and success) else 0,
            1 if (check and not success) else 0,
            1 if repair else 0,
            1 if (repair and success) else 0,
            1 if (repair and not success) else 0,
            timestamp if check else None,
            success, timestamp,
            success, timestamp
        ))
        
        conn.commit()
        conn.close()

    def _save_execution_log(self, execution_id, server_id, service_id, success, manual):
        """Save execution log to database"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO sentinel_logs (execution_id, server_id, service_id, timestamp, level, message, successful)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            execution_id,
            server_id,
            service_id,
            int(datetime.now().timestamp()),
            "info",
            "Manual repair" if manual else "Automated repair",
            1 if success else 0
        ))
        
        conn.commit()
        conn.close()

    def manual_purge(self, days=None, server_id=None, service_name=None, successful_only=False):
        """Purge old logs"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp()) if days else 0
        
        query = "DELETE FROM sentinel_logs WHERE timestamp < ?"
        params = [cutoff]
        
        if server_id:
            query += " AND server_id = ?"
            params.append(server_id)
        
        if service_name:
            query += " AND service_id = ?"
            params.append(service_name)
        
        if successful_only:
            query += " AND successful = 1"
        
        cur.execute(query, params)
        deleted = cur.rowcount
        
        conn.commit()
        conn.close()
        
        return {"success": True, "deleted": deleted}

    def reset_stats(self):
        """Reset all statistics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM sentinel_stats")
        
        conn.commit()
        conn.close()
        
        return {"success": True}

    def get_dashboard_data(self):
        """Get dashboard summary data"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Get stats summary
        cur.execute("""
            SELECT 
                COUNT(*) as total_services,
                SUM(total_checks) as total_checks,
                SUM(successful_checks) as successful_checks,
                SUM(failed_checks) as failed_checks,
                SUM(total_repairs) as total_repairs,
                SUM(successful_repairs) as successful_repairs
            FROM sentinel_stats
        """)
        
        stats = dict(cur.fetchone())
        
        # Calculate success rate
        if stats["total_checks"] > 0:
            stats["success_rate"] = round((stats["successful_checks"] / stats["total_checks"]) * 100, 2)
        else:
            stats["success_rate"] = 0
        
        conn.close()
        return stats

    def get_recent_activity(self, limit=50):
        """Get recent activity log"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM sentinel_logs 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        
        activity = [dict(row) for row in cur.fetchall()]
        conn.close()
        return activity

    def get_health_score(self, server_id):
        """Calculate health score for a server"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                SUM(successful_checks) as successful,
                SUM(total_checks) as total
            FROM sentinel_stats
            WHERE server_id = ?
        """, (server_id,))
        
        result = dict(cur.fetchone())
        conn.close()
        
        if result["total"] > 0:
            return round((result["successful"] / result["total"]) * 100, 2)
        return 0

    # API Routes
    async def api_get_servers(self, request):
        servers = self.load_servers()
        return web.json_response({"servers": servers})

    async def api_add_server(self, request):
        data = await request.json()
        servers = self.load_servers()
        
        if "id" not in data:
            data["id"] = f"server_{int(datetime.now().timestamp())}"
        
        servers.append(data)
        self.save_servers(servers)
        
        return web.json_response({"success": True, "server": data})

    async def api_update_server(self, request):
        server_id = request.match_info["server_id"]
        data = await request.json()
        servers = self.load_servers()
        
        for i, server in enumerate(servers):
            if server["id"] == server_id:
                servers[i] = {**server, **data}
                self.save_servers(servers)
                return web.json_response({"success": True, "server": servers[i]})
        
        return web.json_response({"error": "Server not found"}, status=404)

    async def api_delete_server(self, request):
        server_id = request.match_info["server_id"]
        servers = self.load_servers()
        servers = [s for s in servers if s["id"] != server_id]
        self.save_servers(servers)
        
        return web.json_response({"success": True})

    async def api_get_templates(self, request):
        templates = self.load_templates()
        return web.json_response({"templates": templates})

    async def api_download_template(self, request):
        filename = request.match_info["filename"]
        
        for template_dir in [self.templates_path, self.custom_templates_path]:
            filepath = os.path.join(template_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    template = json.load(f)
                return web.json_response(template)
        
        return web.json_response({"error": "Template not found"}, status=404)

    async def api_upload_template(self, request):
        data = await request.json()
        filename = data.get("filename", f"custom_{int(datetime.now().timestamp())}.json")
        
        filepath = os.path.join(self.custom_templates_path, filename)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        return web.json_response({"success": True, "filename": filename})

    async def api_update_template(self, request):
        filename = request.match_info["filename"]
        data = await request.json()
        
        filepath = os.path.join(self.custom_templates_path, filename)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        return web.json_response({"success": True})

    async def api_delete_template(self, request):
        filename = request.match_info["filename"]
        filepath = os.path.join(self.custom_templates_path, filename)
        
        if os.path.exists(filepath):
            os.remove(filepath)
            return web.json_response({"success": True})
        
        return web.json_response({"error": "Template not found"}, status=404)

    async def api_sync_templates(self, request):
        """Sync templates from GitHub"""
        settings = self.load_settings()
        github_url = settings.get("github_templates_url", "")
        
        if not github_url:
            return web.json_response({"error": "No GitHub URL configured"}, status=400)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(github_url) as resp:
                    if resp.status == 200:
                        templates = await resp.json()
                        
                        for template in templates:
                            filename = template.get("filename", f"template_{int(datetime.now().timestamp())}.json")
                            filepath = os.path.join(self.templates_path, filename)
                            
                            with open(filepath, "w") as f:
                                json.dump(template, f, indent=2)
                        
                        return web.json_response({"success": True, "synced": len(templates)})
                    else:
                        return web.json_response({"error": f"HTTP {resp.status}"}, status=resp.status)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def api_get_settings(self, request):
        settings = self.load_settings()
        return web.json_response(settings)

    async def api_update_settings(self, request):
        data = await request.json()
        settings = self.load_settings()
        settings.update(data)
        self.save_settings(settings)
        return web.json_response({"success": True})

    async def api_get_monitoring(self, request):
        monitoring = self.load_monitoring()
        return web.json_response({"monitoring": monitoring})

    async def api_add_monitoring(self, request):
        data = await request.json()
        monitoring = self.load_monitoring()
        monitoring.append(data)
        self.save_monitoring(monitoring)
        return web.json_response({"success": True})

    async def api_update_monitoring(self, request):
        server_id = request.match_info["server_id"]
        data = await request.json()
        monitoring = self.load_monitoring()
        
        for i, config in enumerate(monitoring):
            if config["server_id"] == server_id:
                monitoring[i] = {**config, **data}
                self.save_monitoring(monitoring)
                return web.json_response({"success": True})
        
        return web.json_response({"error": "Monitoring config not found"}, status=404)

    async def api_delete_monitoring(self, request):
        server_id = request.match_info["server_id"]
        monitoring = self.load_monitoring()
        monitoring = [m for m in monitoring if m["server_id"] != server_id]
        self.save_monitoring(monitoring)
        return web.json_response({"success": True})

    async def api_disable_service(self, request):
        server_id = request.match_info["server_id"]
        service_id = request.match_info["service_id"]
        monitoring = self.load_monitoring()
        
        for config in monitoring:
            if config["server_id"] == server_id:
                for service in config.get("services", []):
                    if service["service_id"] == service_id:
                        service["enabled"] = False
                        self.save_monitoring(monitoring)
                        return web.json_response({"success": True})
        
        return web.json_response({"error": "Service not found"}, status=404)

    async def api_get_maintenance(self, request):
        windows = self.load_maintenance()
        return web.json_response({"windows": windows})

    async def api_add_maintenance(self, request):
        data = await request.json()
        windows = self.load_maintenance()
        
        if "id" not in data:
            data["id"] = f"maint_{int(datetime.now().timestamp())}"
        
        windows.append(data)
        self.save_maintenance(windows)
        return web.json_response({"success": True, "window": data})

    async def api_update_maintenance(self, request):
        window_id = request.match_info["window_id"]
        data = await request.json()
        windows = self.load_maintenance()
        
        for i, window in enumerate(windows):
            if window["id"] == window_id:
                windows[i] = {**window, **data}
                self.save_maintenance(windows)
                return web.json_response({"success": True})
        
        return web.json_response({"error": "Window not found"}, status=404)

    async def api_delete_maintenance(self, request):
        window_id = request.match_info["window_id"]
        windows = self.load_maintenance()
        windows = [w for w in windows if w["id"] != window_id]
        self.save_maintenance(windows)
        return web.json_response({"success": True})

    async def api_get_quiet_hours(self, request):
        config = self.load_quiet_hours()
        return web.json_response(config)

    async def api_update_quiet_hours(self, request):
        data = await request.json()
        self.save_quiet_hours(data)
        return web.json_response({"success": True})

    async def api_dashboard(self, request):
        data = self.get_dashboard_data()
        return web.json_response(data)

    async def api_live_status(self, request):
        """Get live status of all monitored services"""
        status = {
            "monitoring": list(self._monitor_tasks.keys()),
            "services": self._service_states
        }
        return web.json_response(status)

    async def api_recent_activity(self, request):
        limit = int(request.query.get("limit", 50))
        activity = self.get_recent_activity(limit)
        return web.json_response({"activity": activity})

    async def api_health_score(self, request):
        server_id = request.match_info["server_id"]
        score = self.get_health_score(server_id)
        return web.json_response({"server_id": server_id, "health_score": score})

    async def api_log_stream(self, request):
        """WebSocket endpoint for streaming logs"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        execution_id = request.query.get("execution_id")
        
        if execution_id not in self._log_listeners:
            self._log_listeners[execution_id] = []
        
        self._log_listeners[execution_id].append(ws)
        
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == "close":
                        break
        finally:
            self._log_listeners[execution_id].remove(ws)
        
        return ws

    async def api_log_history(self, request):
        """Get log history"""
        limit = int(request.query.get("limit", 100))
        server_id = request.query.get("server_id")
        service_id = request.query.get("service_id")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        query = "SELECT * FROM sentinel_logs"
        params = []
        conditions = []
        
        if server_id:
            conditions.append("server_id = ?")
            params.append(server_id)
        
        if service_id:
            conditions.append("service_id = ?")
            params.append(service_id)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cur.execute(query, params)
        logs = [dict(row) for row in cur.fetchall()]
        
        conn.close()
        return web.json_response({"logs": logs})

    async def api_execution_logs(self, request):
        """Get logs for a specific execution"""
        execution_id = request.match_info["execution_id"]
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM sentinel_logs 
            WHERE execution_id = ?
            ORDER BY timestamp ASC
        """, (execution_id,))
        
        logs = [dict(row) for row in cur.fetchall()]
        conn.close()
        
        return web.json_response({"logs": logs})

    async def api_delete_logs(self, request):
        """Delete logs for a specific execution"""
        execution_id = request.match_info["execution_id"]
        
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM sentinel_logs WHERE execution_id = ?", (execution_id,))
        deleted = cur.rowcount
        
        conn.commit()
        conn.close()
        
        return web.json_response({"success": True, "deleted": deleted})

    async def api_manual_check(self, request):
        """Manual service check"""
        data = await request.json()
        
        server_id = data.get("server_id")
        service_id = data.get("service_id")
        
        if not server_id or not service_id:
            return web.json_response({"error": "server_id and service_id required"}, status=400)
        
        servers = self.load_servers()
        server = next((s for s in servers if s["id"] == server_id), None)
        if not server:
            return web.json_response({"error": "Server not found"}, status=404)
        
        template = self.get_template(service_id)
        if not template:
            return web.json_response({"error": "Template not found"}, status=404)
        
        check_command = template.get("check_command")
        if not check_command:
            return web.json_response({"error": "No check command in template"}, status=400)
        
        result = await self._run_ssh_command(server, check_command)
        expected = template.get("expected_output", "")
        success = self._check_success(result, expected)
        
        return web.json_response({
            "success": success,
            "output": result.get("stdout", ""),
            "error": result.get("stderr", "") if not success else None
        })

    async def api_manual_repair(self, request):
        """Manual service repair"""
        data = await request.json()
        
        server_id = data.get("server_id")
        service_id = data.get("service_id")
        
        if not server_id or not service_id:
            return web.json_response({"error": "server_id and service_id required"}, status=400)
        
        servers = self.load_servers()
        server = next((s for s in servers if s["id"] == server_id), None)
        if not server:
            return web.json_response({"error": "Server not found"}, status=404)
        
        template = self.get_template(service_id)
        if not template:
            return web.json_response({"error": "Template not found"}, status=404)
        
        execution_id = f"manual_repair_{server_id}_{service_id}_{int(datetime.now().timestamp())}"
        asyncio.create_task(self.repair_service(server, template, execution_id=execution_id, manual=True))
        
        return web.json_response({
            "execution_id": execution_id,
            "stream_url": f"/api/sentinel/logs/stream?execution_id={execution_id}"
        })

    async def api_start_monitoring(self, request):
        server_id = request.match_info["server_id"]
        self.start_monitoring(server_id)
        return web.json_response({"success": True})

    async def api_stop_monitoring(self, request):
        server_id = request.match_info["server_id"]
        self.stop_monitoring(server_id)
        return web.json_response({"success": True})

    async def api_start_all(self, request):
        self.start_all_monitoring()
        return web.json_response({"success": True})

    async def api_manual_purge(self, request):
        data = await request.json()
        result = self.manual_purge(
            days=data.get("days"),
            server_id=data.get("server_id"),
            service_name=data.get("service_name"),
            successful_only=data.get("successful_only", False)
        )
        return web.json_response(result)

    async def api_reset_stats(self, request):
        result = self.reset_stats()
        return web.json_response(result)

    def setup_routes(self, app):
        # Server management
        app.router.add_get("/api/sentinel/servers", self.api_get_servers)
        app.router.add_post("/api/sentinel/servers", self.api_add_server)
        app.router.add_put("/api/sentinel/servers/{server_id}", self.api_update_server)
        app.router.add_delete("/api/sentinel/servers/{server_id}", self.api_delete_server)
        
        # Template management
        app.router.add_get("/api/sentinel/templates", self.api_get_templates)
        app.router.add_get("/api/sentinel/templates/{filename}", self.api_download_template)
        app.router.add_post("/api/sentinel/templates", self.api_upload_template)
        app.router.add_put("/api/sentinel/templates/{filename}", self.api_update_template)
        app.router.add_delete("/api/sentinel/templates/{filename}", self.api_delete_template)
        app.router.add_post("/api/sentinel/templates/sync", self.api_sync_templates)
        
        # Settings
        app.router.add_get("/api/sentinel/settings", self.api_get_settings)
        app.router.add_put("/api/sentinel/settings", self.api_update_settings)
        
        # Monitoring configuration
        app.router.add_get("/api/sentinel/monitoring", self.api_get_monitoring)
        app.router.add_post("/api/sentinel/monitoring", self.api_add_monitoring)
        app.router.add_put("/api/sentinel/monitoring/{server_id}", self.api_update_monitoring)
        app.router.add_delete("/api/sentinel/monitoring/{server_id}", self.api_delete_monitoring)
        app.router.add_post("/api/sentinel/monitoring/{server_id}/disable/{service_id}", self.api_disable_service)
        
        # Maintenance windows
        app.router.add_get("/api/sentinel/maintenance", self.api_get_maintenance)
        app.router.add_post("/api/sentinel/maintenance", self.api_add_maintenance)
        app.router.add_put("/api/sentinel/maintenance/{window_id}", self.api_update_maintenance)
        app.router.add_delete("/api/sentinel/maintenance/{window_id}", self.api_delete_maintenance)
        
        # Quiet hours
        app.router.add_get("/api/sentinel/quiet-hours", self.api_get_quiet_hours)
        app.router.add_put("/api/sentinel/quiet-hours", self.api_update_quiet_hours)
        
        # Dashboard and status
        app.router.add_get("/api/sentinel/dashboard", self.api_dashboard)
        app.router.add_get("/api/sentinel/status", self.api_live_status)
        app.router.add_get("/api/sentinel/activity", self.api_recent_activity)
        app.router.add_get("/api/sentinel/health/{server_id}", self.api_health_score)
        
        # Logs
        app.router.add_get("/api/sentinel/logs/stream", self.api_log_stream)
        app.router.add_get("/api/sentinel/logs/history", self.api_log_history)
        app.router.add_get("/api/sentinel/logs/execution/{execution_id}", self.api_execution_logs)
        app.router.add_delete("/api/sentinel/logs/{execution_id}", self.api_delete_logs)
        
        # Manual operations
        app.router.add_post("/api/sentinel/test/check", self.api_manual_check)
        app.router.add_post("/api/sentinel/test/repair", self.api_manual_repair)
        
        # Monitoring control
        app.router.add_post("/api/sentinel/start/{server_id}", self.api_start_monitoring)
        app.router.add_post("/api/sentinel/stop/{server_id}", self.api_stop_monitoring)
        app.router.add_post("/api/sentinel/start-all", self.api_start_all)
        
        # Utility
        app.router.add_post("/api/sentinel/purge", self.api_manual_purge)
        app.router.add_post("/api/sentinel/reset-stats", self.api_reset_stats)
        
        # NEW: Auto-heal endpoints
        app.router.add_post("/api/sentinel/trigger", self.api_analytics_trigger)
        app.router.add_get("/api/sentinel/heal/templates", self.api_get_heal_templates)
        app.router.add_post("/api/sentinel/heal/templates", self.api_add_heal_template)
        app.router.add_put("/api/sentinel/heal/templates/{template_id}", self.api_update_heal_template)
        app.router.add_delete("/api/sentinel/heal/templates/{template_id}", self.api_delete_heal_template)
        app.router.add_get("/api/sentinel/heal/presets", self.api_get_presets)
        app.router.add_post("/api/sentinel/heal/presets", self.api_add_custom_preset)
        app.router.add_get("/api/sentinel/heal/history", self.api_get_heal_history)
