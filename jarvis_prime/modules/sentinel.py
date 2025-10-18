#!/usr/bin/env python3
# /app/sentinel.py
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

import json, os

def ensure_sentinel_defaults(base="/share/jarvis_prime/sentinel"):
    os.makedirs(base, exist_ok=True)
    defaults = {
        "settings.json": {
            "check_interval": 300,
            "notify_on_failure": True,
            "notify_recovery": True,
            "auto_reload_templates": True,
            "github_templates_url": ""
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

logger = logging.getLogger(__name__)

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
        
        # CRITICAL FIX: Thread pool for blocking SSH operations
        self._ssh_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sentinel_ssh")
        
        self.init_storage()
        self.init_db()

    def init_storage(self):
        """Initialize storage directories and files"""
        os.makedirs(self.data_path, exist_ok=True)
        os.makedirs(self.custom_templates_path, exist_ok=True)
        os.makedirs(self.templates_path, exist_ok=True)
        
        for filename in ["servers.json", "monitoring.json", "maintenance_windows.json", "quiet_hours.json", "settings.json"]:
            filepath = os.path.join(self.data_path, filename)
            if not os.path.exists(filepath):
                default = {"github_templates_url": ""} if filename == "settings.json" else []
                with open(filepath, "w") as f:
                    json.dump(default, f)

    def load_settings(self):
        """Load Sentinel settings including GitHub URL"""
        filepath = os.path.join(self.data_path, "settings.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {"github_templates_url": ""}

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
        """Initialize SQLite database for logging"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                server_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                status TEXT NOT NULL,
                response_time REAL,
                output TEXT
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_repairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                server_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                success INTEGER NOT NULL,
                attempts INTEGER NOT NULL,
                output TEXT
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                server_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                reason TEXT,
                notified INTEGER DEFAULT 0
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_checks INTEGER,
                services_monitored INTEGER,
                services_down INTEGER,
                repairs_made INTEGER,
                failed_repairs INTEGER
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                server_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                action TEXT NOT NULL,
                command TEXT,
                output TEXT,
                exit_code INTEGER,
                manual_trigger INTEGER DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()

    # Server Management
    def load_servers(self):
        filepath = os.path.join(self.data_path, "servers.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Error loading servers: {e}")
            return []

    def save_servers(self, servers):
        filepath = os.path.join(self.data_path, "servers.json")
        try:
            with open(filepath, "w") as f:
                json.dump(servers, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving servers: {e}")
            return False

    def add_server(self, server_id, host, port, username, password, description=""):
        servers = self.load_servers()
        if any(s["id"] == server_id for s in servers):
            return {"success": False, "error": "Server ID already exists"}
        
        servers.append({
            "id": server_id,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "description": description,
            "added": datetime.now().isoformat()
        })
        
        if self.save_servers(servers):
            return {"success": True}
        return {"success": False, "error": "Failed to save server"}

    def update_server(self, server_id, updates):
        servers = self.load_servers()
        for server in servers:
            if server["id"] == server_id:
                server.update(updates)
                if self.save_servers(servers):
                    return {"success": True}
                return {"success": False, "error": "Failed to save changes"}
        return {"success": False, "error": "Server not found"}

    def delete_server(self, server_id):
        servers = self.load_servers()
        servers = [s for s in servers if s["id"] != server_id]
        if self.save_servers(servers):
            monitoring = self.load_monitoring()
            monitoring = [m for m in monitoring if m["server_id"] != server_id]
            self.save_monitoring(monitoring)
            return {"success": True}
        return {"success": False, "error": "Failed to delete server"}

    # Template Management
    def load_templates(self):
        templates = []
        
        if os.path.exists(self.templates_path):
            for filename in os.listdir(self.templates_path):
                if filename.endswith(".json"):
                    filepath = os.path.join(self.templates_path, filename)
                    try:
                        with open(filepath, "r") as f:
                            template = json.load(f)
                            template["source"] = "default"
                            template["filename"] = filename
                            templates.append(template)
                    except Exception as e:
                        self.logger(f"Error loading template {filename}: {e}")
        
        if os.path.exists(self.custom_templates_path):
            for filename in os.listdir(self.custom_templates_path):
                if filename.endswith(".json"):
                    filepath = os.path.join(self.custom_templates_path, filename)
                    try:
                        with open(filepath, "r") as f:
                            template = json.load(f)
                            template["source"] = "custom"
                            template["filename"] = filename
                            templates.append(template)
                    except Exception as e:
                        self.logger(f"Error loading custom template {filename}: {e}")
			# --- Deduplicate templates by ID or name (fix for duplicates from GitHub + local) ---
        seen = {}
        for tpl in templates:
            key = tpl.get("id") or tpl.get("name") or tpl.get("filename")
            if key not in seen:
                seen[key] = tpl
        templates = list(seen.values())
			
        
        # --- Sort templates alphabetically by name (case-insensitive) ---
        templates.sort(key=lambda t: (t.get("name") or t.get("id") or "").lower())
        return templates

    def get_template(self, template_name):
        templates = self.load_templates()
        for t in templates:
            if t.get("id") == template_name or t.get("name") == template_name:
                return t
        return None

    def save_template(self, template_data, filename=None):
        if not filename:
            filename = f"{template_data.get('id', 'custom')}.json"
        
        if not filename.endswith(".json"):
            filename += ".json"
        
        filepath = os.path.join(self.custom_templates_path, filename)
        try:
            with open(filepath, "w") as f:
                json.dump(template_data, f, indent=2)
            return {"success": True, "filename": filename}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_template(self, filename):
        filepath = os.path.join(self.custom_templates_path, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Template not found"}

    def upload_template(self, content, filename):
        if not filename.endswith(".json"):
            return {"success": False, "error": "Template must be a .json file"}
        
        try:
            template_data = json.loads(content)
            required_fields = ["id", "name", "check_cmd"]
            if not all(field in template_data for field in required_fields):
                return {"success": False, "error": "Template missing required fields"}
            
            return self.save_template(template_data, filename)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON format"}

    def download_template(self, filename):
        filepath = os.path.join(self.custom_templates_path, filename)
        if not os.path.exists(filepath):
            filepath = os.path.join(self.templates_path, filename)
        
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    return {"success": True, "content": f.read()}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Template not found"}

    async def sync_github_templates(self, custom_url=None):
        """Sync templates from GitHub - uses stored URL or custom URL"""
        settings = self.load_settings()
        github_url = custom_url or settings.get("github_templates_url") or self.config.get("github_templates_url")
        
        if not github_url:
            return {"success": False, "error": "No GitHub URL configured", "skipped": True}
        
        if custom_url and custom_url != settings.get("github_templates_url"):
            settings["github_templates_url"] = custom_url
            self.save_settings(settings)
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                repo_api = github_url
                
                if "github.com" in repo_api and "/contents/" not in repo_api:
                    parts = repo_api.replace("https://github.com/", "").split("/")
                    if len(parts) >= 2:
                        user, repo = parts[0], parts[1]
                        path = "/".join(parts[4:]) if len(parts) > 4 else ""
                        repo_api = f"https://api.github.com/repos/{user}/{repo}/contents/{path}"
                
                try:
                    async with session.get(repo_api) as resp:
                        if resp.status != 200:
                            return {"success": False, "error": f"GitHub API returned {resp.status}", "skipped": True}
                        
                        files = await resp.json()
                except asyncio.TimeoutError:
                    return {"success": False, "error": "Timeout connecting to GitHub", "skipped": True}
                except aiohttp.ClientError as e:
                    return {"success": False, "error": f"Connection error: {e}", "skipped": True}
                
                downloaded = []
                updated = []
                failed = []
                
                for file_info in files:
                    if not file_info.get("name", "").endswith(".json"):
                        continue
                    
                    filename = file_info["name"]
                    download_url = file_info.get("download_url")
                    
                    if not download_url:
                        continue
                    
                    try:
                        async with session.get(download_url) as resp:
                            if resp.status == 200:
                                content = await resp.text()
                                template_data = json.loads(content)
                                local_path = os.path.join(self.templates_path, filename)
                                exists = os.path.exists(local_path)
                                
                                with open(local_path, "w") as f:
                                    f.write(content)
                                
                                if exists:
                                    updated.append(filename)
                                else:
                                    downloaded.append(filename)
                                
                                self.logger(f"[sentinel] Synced template: {filename}")
                            else:
                                failed.append(filename)
                    
                    except Exception as e:
                        self.logger(f"[sentinel] Failed to sync {filename}: {e}")
                        failed.append(filename)
                
                return {
                    "success": True,
                    "downloaded": downloaded,
                    "updated": updated,
                    "failed": failed,
                    "total": len(downloaded) + len(updated)
                }
        
        except Exception as e:
            self.logger(f"[sentinel] GitHub sync failed: {e}")
            return {"success": False, "error": str(e), "skipped": True}

    async def auto_sync_templates(self):
        if not self.config.get("auto_update_templates", False):
            self.logger("[sentinel] Auto-update templates disabled")
            return
        
        update_interval = self.config.get("update_interval_hours", 24)
        
        while True:
            try:
                self.logger("[sentinel] Starting automatic template sync...")
                result = await self.sync_github_templates()
                
                if result.get("skipped"):
                    self.logger("[sentinel] Template sync skipped (no internet or GitHub unavailable)")
                elif result["success"]:
                    total = result.get("total", 0)
                    if total > 0:
                        if self.notify_callback:
                            try:
                                await self.notify_callback(
                                    title="Sentinel Templates Updated",
                                    body=f"Synced {total} templates from GitHub",
                                    source="sentinel",
                                    priority=3
                                )
                            except Exception:
                                pass
                        self.logger(f"[sentinel] Auto-sync complete: {total} templates updated")
                    else:
                        self.logger("[sentinel] Auto-sync complete: No new templates")
                else:
                    self.logger(f"[sentinel] Auto-sync failed but Sentinel continues: {result.get('error')}")
                
                await asyncio.sleep(update_interval * 3600)
            
            except Exception as e:
                self.logger(f"[sentinel] Auto-sync error (non-fatal): {e}")
                await asyncio.sleep(3600)

    def load_monitoring(self):
        filepath = os.path.join(self.data_path, "monitoring.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Error loading monitoring config: {e}")
            return []

    def save_monitoring(self, monitoring):
        filepath = os.path.join(self.data_path, "monitoring.json")
        try:
            with open(filepath, "w") as f:
                json.dump(monitoring, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving monitoring config: {e}")
            return False

    def add_monitoring(self, server_id, services, check_interval=300, service_intervals=None):
        monitoring = self.load_monitoring()
        monitoring = [m for m in monitoring if m["server_id"] != server_id]
        
        monitoring.append({
            "server_id": server_id,
            "services": services,
            "check_interval": check_interval,
            "service_intervals": service_intervals or {},
            "enabled": True,
            "dependencies": {},
            "disabled_until": None
        })
        
        if self.save_monitoring(monitoring):
            return {"success": True}
        return {"success": False, "error": "Failed to save monitoring config"}

    def update_monitoring(self, server_id, updates):
        monitoring = self.load_monitoring()
        for mon in monitoring:
            if mon["server_id"] == server_id:
                mon.update(updates)
                if self.save_monitoring(monitoring):
                    return {"success": True}
                return {"success": False, "error": "Failed to save changes"}
        return {"success": False, "error": "Monitoring config not found"}

    def delete_monitoring(self, server_id):
        monitoring = self.load_monitoring()
        monitoring = [m for m in monitoring if m["server_id"] != server_id]
        if self.save_monitoring(monitoring):
            if server_id in self._monitor_tasks:
                self._monitor_tasks[server_id].cancel()
                del self._monitor_tasks[server_id]
            return {"success": True}
        return {"success": False, "error": "Failed to delete monitoring"}

    def get_service_interval(self, mon_config, service_id):
        service_intervals = mon_config.get("service_intervals", {})
        return service_intervals.get(service_id, mon_config.get("check_interval", 300))

    def disable_service_temporarily(self, server_id, service_id, duration_hours=2):
        monitoring = self.load_monitoring()
        for mon in monitoring:
            if mon["server_id"] == server_id:
                if "disabled_services" not in mon:
                    mon["disabled_services"] = {}
                
                until = (datetime.now() + timedelta(hours=duration_hours)).isoformat()
                mon["disabled_services"][service_id] = until
                
                if self.save_monitoring(monitoring):
                    return {"success": True, "disabled_until": until}
                return {"success": False, "error": "Failed to save changes"}
        return {"success": False, "error": "Monitoring config not found"}

    def load_maintenance_windows(self):
        filepath = os.path.join(self.data_path, "maintenance_windows.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Error loading maintenance windows: {e}")
            return []

    def save_maintenance_windows(self, windows):
        filepath = os.path.join(self.data_path, "maintenance_windows.json")
        try:
            with open(filepath, "w") as f:
                json.dump(windows, f, indent=2)
            return True
        except Exception as e:
            self.logger(f"Error saving maintenance windows: {e}")
            return False

    def is_in_maintenance_window(self, server_id=None):
        windows = self.load_maintenance_windows()
        now = datetime.now()
        current_time = now.time()
        current_day = now.strftime("%A").lower()
        
        for window in windows:
            if not window.get("enabled", True):
                continue
            
            if server_id and window.get("server_id") and window["server_id"] != server_id:
                continue
            
            days = window.get("days", [])
            if days and current_day not in [d.lower() for d in days]:
                continue
            
            start_time = datetime.strptime(window["start_time"], "%H:%M").time()
            end_time = datetime.strptime(window["end_time"], "%H:%M").time()
            
            if start_time <= current_time <= end_time:
                return True
        
        return False

    def load_quiet_hours(self):
        filepath = os.path.join(self.data_path, "quiet_hours.json")
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Error loading quiet hours: {e}")
            return {"enabled": False, "start": "22:00", "end": "08:00"}

    def is_quiet_hours(self):
        config = self.load_quiet_hours()
        if not config.get("enabled", False):
            return False
        
        now = datetime.now().time()
        start = datetime.strptime(config["start"], "%H:%M").time()
        end = datetime.strptime(config["end"], "%H:%M").time()
        
        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end

    def _log_to_db(self, execution_id, server_id, service_name, action, command, output, exit_code, manual=False):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO sentinel_logs (execution_id, timestamp, server_id, service_name, action, command, output, exit_code, manual_trigger)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                execution_id,
                datetime.now().isoformat(),
                server_id,
                service_name,
                action,
                command,
                output,
                exit_code,
                1 if manual else 0
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger(f"[sentinel] Failed to log to DB: {e}")

    def _broadcast_log(self, execution_id, log_entry):
        if execution_id in self._log_listeners:
            dead = []
            for queue in list(self._log_listeners[execution_id]):
                try:
                    queue.put_nowait(log_entry)
                except Exception:
                    dead.append(queue)
            for q in dead:
                self._log_listeners[execution_id].discard(q)

    # CRITICAL FIX: Run blocking SSH operations in thread pool
    def _ssh_execute_blocking(self, server, command):
        """Blocking SSH execution - runs in thread pool"""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            client.connect(
                hostname=server["host"],
                port=server["port"],
                username=server["username"],
                password=server["password"],
                timeout=10
            )
            
            stdin, stdout, stderr = client.exec_command(command)
            
            output_lines = []
            for line in stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)
            
            error_lines = []
            for line in stderr:
                line = line.strip()
                if line:
                    error_lines.append(line)
            
            exit_code = stdout.channel.recv_exit_status()
            client.close()
            
            full_output = "\n".join(output_lines) if output_lines else "\n".join(error_lines)
            
            return {
                "success": exit_code == 0,
                "output": full_output,
                "exit_code": exit_code,
                "output_lines": output_lines,
                "error_lines": error_lines
            }
            
        except Exception as e:
            error_msg = str(e)
            return {
                "success": False,
                "output": error_msg,
                "exit_code": -1,
                "output_lines": [],
                "error_lines": [error_msg]
            }
        finally:
            try:
                client.close()
            except:
                pass

    async def ssh_execute(self, server, command, execution_id=None, service_name="", action="execute", manual=False):
        """Async wrapper - runs SSH in thread pool to prevent blocking"""
        server_id = server.get("id", "unknown")
        
        if not execution_id:
            execution_id = f"{server_id}_{int(datetime.now().timestamp())}"
        
        start_log = {
            "type": "command",
            "timestamp": datetime.now().isoformat(),
            "server_id": server_id,
            "service": service_name,
            "action": action,
            "command": command
        }
        self._broadcast_log(execution_id, start_log)
        
        # Run blocking SSH in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self._ssh_executor,
            self._ssh_execute_blocking,
            server,
            command
        )
        
        # Broadcast output line by line
        for line in result.get("output_lines", []):
            line_log = {
                "type": "output",
                "timestamp": datetime.now().isoformat(),
                "line": line
            }
            self._broadcast_log(execution_id, line_log)
        
        for line in result.get("error_lines", []):
            error_log = {
                "type": "error",
                "timestamp": datetime.now().isoformat(),
                "line": line
            }
            self._broadcast_log(execution_id, error_log)
        
        self._log_to_db(execution_id, server_id, service_name, action, command, result["output"], result["exit_code"], manual)
        
        complete_log = {
            "type": "complete",
            "timestamp": datetime.now().isoformat(),
            "exit_code": result["exit_code"],
            "success": result["success"]
        }
        self._broadcast_log(execution_id, complete_log)
        
        result["execution_id"] = execution_id
        return result

    async def check_service(self, server, service_template, execution_id=None, manual=False):
        start_time = datetime.now()
        
        result = await self.ssh_execute(
            server, 
            service_template["check_cmd"],
            execution_id=execution_id,
            service_name=service_template["name"],
            action="check",
            manual=manual
        )
        
        response_time = (datetime.now() - start_time).total_seconds()
        expected = service_template.get("expected_output", "")
        is_healthy = result["success"] and (not expected or expected in result["output"])
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO sentinel_checks (timestamp, server_id, service_name, status, response_time, output)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            server["id"],
            service_template["name"],
            "healthy" if is_healthy else "unhealthy",
            response_time,
            result["output"]
        ))
        conn.commit()
        conn.close()
        
        return {
            "healthy": is_healthy,
            "output": result["output"],
            "response_time": response_time,
            "execution_id": result.get("execution_id")
        }

    async def repair_service(self, server, service_template, execution_id=None, manual=False):
        max_attempts = service_template.get("retry_count", 2)
        retry_delay = service_template.get("retry_delay", 30)
        
        for attempt in range(1, max_attempts + 1):
            self.logger(f"Repair attempt {attempt}/{max_attempts} for {service_template['name']} on {server['id']}")
            
            fix_result = await self.ssh_execute(
                server, 
                service_template["fix_cmd"],
                execution_id=execution_id,
                service_name=service_template["name"],
                action=f"repair_attempt_{attempt}",
                manual=manual
            )
            
            await asyncio.sleep(retry_delay)
            
            verify_cmd = service_template.get("verify_cmd", service_template["check_cmd"])
            verify_result = await self.ssh_execute(
                server, 
                verify_cmd,
                execution_id=execution_id,
                service_name=service_template["name"],
                action=f"verify_attempt_{attempt}",
                manual=manual
            )
            
            expected = service_template.get("expected_output", "")
            is_fixed = verify_result["success"] and (not expected or expected in verify_result["output"])
            
            if is_fixed:
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                c.execute("""
                    INSERT INTO sentinel_repairs (timestamp, server_id, service_name, success, attempts, output)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    server["id"],
                    service_template["name"],
                    1,
                    attempt,
                    verify_result["output"]
                ))
                conn.commit()
                conn.close()
                
                return {
                    "success": True, 
                    "attempts": attempt, 
                    "output": verify_result["output"],
                    "execution_id": verify_result.get("execution_id")
                }
            
            if attempt < max_attempts:
                await asyncio.sleep(retry_delay)
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO sentinel_repairs (timestamp, server_id, service_name, success, attempts, output)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            server["id"],
            service_template["name"],
            0,
            max_attempts,
            "All repair attempts failed"
        ))
        c.execute("""
            INSERT INTO sentinel_failures (timestamp, server_id, service_name, reason, notified)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            server["id"],
            service_template["name"],
            "Failed to repair after multiple attempts",
            0
        ))
        conn.commit()
        conn.close()
        
        return {
            "success": False, 
            "attempts": max_attempts,
            "execution_id": execution_id
        }

    async def monitor_service(self, server, service_template, monitoring_config):
        server_id = server["id"]
        service_id = service_template["id"]
        service_name = service_template["name"]
        state_key = f"{server_id}:{service_id}"
        
        disabled_services = monitoring_config.get("disabled_services", {})
        if service_id in disabled_services:
            until = datetime.fromisoformat(disabled_services[service_id])
            if datetime.now() < until:
                self.logger(f"Service {service_name} on {server_id} is disabled until {until}")
                return
            else:
                del disabled_services[service_id]
                self.save_monitoring(self.load_monitoring())
        
        if self.is_in_maintenance_window(server_id):
            self.logger(f"Server {server_id} is in maintenance window, skipping checks")
            return
        
        dependencies = monitoring_config.get("dependencies", {}).get(service_id, [])
        for parent_service in dependencies:
            parent_state_key = f"{server_id}:{parent_service}"
            if self._service_states.get(parent_state_key) == "down":
                self.logger(f"Skipping {service_name} on {server_id} - parent service {parent_service} is down")
                return
        
        check_result = await self.check_service(server, service_template)
        
        if check_result["healthy"]:
            self._service_states[state_key] = "up"
            self._failure_counts[state_key] = 0
            
            if self._service_states.get(f"{state_key}:was_down"):
                await self._send_notification(
                    f"✅ Service Recovered: {service_name}",
                    f"Service {service_name} on {server_id} is now healthy",
                    priority=3
                )
                del self._service_states[f"{state_key}:was_down"]
        else:
            self.logger(f"Service {service_name} on {server_id} appears down, double-checking...")
            await asyncio.sleep(30)
            
            recheck_result = await self.check_service(server, service_template)
            
            if recheck_result["healthy"]:
                self.logger(f"Service {service_name} on {server_id} recovered on recheck")
                self._service_states[state_key] = "up"
                return
            
            self._service_states[state_key] = "down"
            self._service_states[f"{state_key}:was_down"] = True
            self._failure_counts[state_key] = self._failure_counts.get(state_key, 0) + 1
            failure_count = self._failure_counts[state_key]
            
            if failure_count == 1:
                self.logger(f"First failure for {service_name} on {server_id}, attempting repair...")
                repair_result = await self.repair_service(server, service_template)
                
                if repair_result["success"]:
                    await self._send_notification(
                        f"✅ Auto-Repair Successful: {service_name}",
                        f"Service {service_name} on {server_id} was down and has been repaired automatically",
                        priority=3
                    )
                    self._service_states[state_key] = "up"
                    self._failure_counts[state_key] = 0
                    del self._service_states[f"{state_key}:was_down"]
                
            elif failure_count == 2:
                if not self.is_quiet_hours():
                    await self._send_notification(
                        f"⚠️ Service Down: {service_name}",
                        f"Service {service_name} on {server_id} is down (2nd failure). Auto-repair in progress...",
                        priority=5
                    )
                repair_result = await self.repair_service(server, service_template)
                
            else:
                await self._send_notification(
                    f"❌ CRITICAL: {service_name}",
                    f"Service {service_name} on {server_id} has failed {failure_count} times and cannot be repaired automatically",
                    priority=8
                )

    async def _send_notification(self, title, body, priority=5):
        """Unified notification fan-out through Jarvis Prime"""
        try:
            # 1️⃣ Route through Jarvis Prime’s global message router first
            try:
                from bot import process_incoming
                process_incoming(title, body, source="sentinel", priority=priority)
            except Exception as e:
                self.logger(f"[sentinel] process_incoming fan-out failed: {e}")

            # 2️⃣ Legacy notify_callback (kept for backward compatibility)
            if self.notify_callback:
                await self.notify_callback(
                    title=title,
                    body=body,
                    source="sentinel",
                    priority=priority
                )
        except Exception as e:
            self.logger(f"[sentinel] Failed to send notification: {e}")

    async def monitor_loop(self, server_id):
        while True:
            try:
                servers = self.load_servers()
                server = next((s for s in servers if s["id"] == server_id), None)
                
                if not server:
                    self.logger(f"Server {server_id} not found, stopping monitor")
                    break
                
                monitoring = self.load_monitoring()
                mon_config = next((m for m in monitoring if m["server_id"] == server_id), None)
                
                if not mon_config or not mon_config.get("enabled", True):
                    self.logger(f"Monitoring disabled for {server_id}")
                    await asyncio.sleep(60)
                    continue
                
                services = mon_config.get("services", [])
                
                for service_id in services:
                    template = self.get_template(service_id)
                    if template:
                        await self.monitor_service(server, template, mon_config)
                    else:
                        self.logger(f"Template {service_id} not found")
                
                default_interval = mon_config.get("check_interval", 300)
                await asyncio.sleep(default_interval)
                
            except Exception as e:
                self.logger(f"Error in monitor loop for {server_id}: {e}")
                await asyncio.sleep(60)

    def start_monitoring(self, server_id):
        if server_id not in self._monitor_tasks:
            task = asyncio.create_task(self.monitor_loop(server_id))
            self._monitor_tasks[server_id] = task
            self.logger(f"Started monitoring for {server_id}")

    def stop_monitoring(self, server_id):
        if server_id in self._monitor_tasks:
            self._monitor_tasks[server_id].cancel()
            del self._monitor_tasks[server_id]
            self.logger(f"Stopped monitoring for {server_id}")

    def start_all_monitoring(self):
        monitoring = self.load_monitoring()
        for mon_config in monitoring:
            if mon_config.get("enabled", True):
                self.start_monitoring(mon_config["server_id"])

    def get_dashboard_metrics(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM sentinel_checks")
        total_checks = c.fetchone()[0]
        
        today = datetime.now().date().isoformat()
        c.execute("SELECT COUNT(*) FROM sentinel_checks WHERE DATE(timestamp) = ?", (today,))
        checks_today = c.fetchone()[0]
        
        monitoring = self.load_monitoring()
        services_monitored = sum(len(m.get("services", [])) for m in monitoring if m.get("enabled", True))
        services_down = sum(1 for state in self._service_states.values() if state == "down")
        
        c.execute("SELECT COUNT(*) FROM sentinel_repairs WHERE success = 1")
        repairs_all_time = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM sentinel_repairs WHERE success = 1 AND DATE(timestamp) = ?", (today,))
        repairs_today = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM sentinel_repairs WHERE success = 0")
        failed_repairs = c.fetchone()[0]
        
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        c.execute("SELECT COUNT(*) FROM sentinel_checks WHERE timestamp > ?", (yesterday,))
        recent_checks = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM sentinel_checks WHERE timestamp > ? AND status = 'healthy'", (yesterday,))
        healthy_checks = c.fetchone()[0]
        
        uptime_percent = (healthy_checks / recent_checks * 100) if recent_checks > 0 else 100
        
        c.execute("SELECT AVG(response_time) FROM sentinel_checks WHERE timestamp > ?", (yesterday,))
        avg_response_time = c.fetchone()[0] or 0
        
        c.execute("""
            SELECT service_name, COUNT(*) as repair_count 
            FROM sentinel_repairs 
            WHERE success = 1 
            GROUP BY service_name 
            ORDER BY repair_count DESC 
            LIMIT 1
        """)
        most_repaired = c.fetchone()
        
        servers_monitored = len([m for m in monitoring if m.get("enabled", True)])
        active_schedules = len(monitoring)
        
        c.execute("SELECT MAX(timestamp) FROM sentinel_checks")
        last_check = c.fetchone()[0]
        
        conn.close()
        
        return {
            "total_checks": total_checks,
            "checks_today": checks_today,
            "services_monitored": services_monitored,
            "services_down": services_down,
            "repairs_all_time": repairs_all_time,
            "repairs_today": repairs_today,
            "failed_repairs": failed_repairs,
            "uptime_percent": round(uptime_percent, 2),
            "avg_response_time": round(avg_response_time, 3),
            "most_repaired_service": most_repaired[0] if most_repaired else "None",
            "most_repaired_count": most_repaired[1] if most_repaired else 0,
            "servers_monitored": servers_monitored,
            "active_schedules": active_schedules,
            "last_check": last_check
        }

    def get_live_status(self):
        servers = self.load_servers()
        monitoring = self.load_monitoring()
        status_list = []
        
        for mon_config in monitoring:
            if not mon_config.get("enabled", True):
                continue
            
            server = next((s for s in servers if s["id"] == mon_config["server_id"]), None)
            if not server:
                continue
            
            for service_id in mon_config.get("services", []):
                template = self.get_template(service_id)
                if not template:
                    continue
                
                state_key = f"{server['id']}:{service_id}"
                status = self._service_states.get(state_key, "unknown")
                
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                c.execute("""
                    SELECT timestamp, status, response_time 
                    FROM sentinel_checks 
                    WHERE server_id = ? AND service_name = ? 
                    ORDER BY timestamp DESC LIMIT 1
                """, (server["id"], template["name"]))
                last_check = c.fetchone()
                conn.close()
                
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                yesterday = (datetime.now() - timedelta(days=1)).isoformat()
                c.execute("""
                    SELECT COUNT(*) FROM sentinel_checks 
                    WHERE server_id = ? AND service_name = ? AND timestamp > ?
                """, (server["id"], template["name"], yesterday))
                total = c.fetchone()[0]
                
                c.execute("""
                    SELECT COUNT(*) FROM sentinel_checks 
                    WHERE server_id = ? AND service_name = ? AND timestamp > ? AND status = 'healthy'
                """, (server["id"], template["name"], yesterday))
                healthy = c.fetchone()[0]
                conn.close()
                
                uptime = (healthy / total * 100) if total > 0 else 0
                
                status_list.append({
                    "server_id": server["id"],
                    "server_name": server.get("description", server["id"]),
                    "service_name": template["name"],
                    "status": status,
                    "last_check": last_check[0] if last_check else None,
                    "response_time": last_check[2] if last_check else None,
                    "uptime_24h": round(uptime, 2)
                })
        
        return status_list

    def get_recent_activity(self, limit=20):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            SELECT 'check' as type, timestamp, server_id, service_name, status as message, NULL as attempts
            FROM sentinel_checks
            WHERE status = 'unhealthy'
            UNION ALL
            SELECT 'repair' as type, timestamp, server_id, service_name, 
                   CASE WHEN success = 1 THEN 'repaired' ELSE 'failed' END as message,
                   attempts
            FROM sentinel_repairs
            UNION ALL
            SELECT 'failure' as type, timestamp, server_id, service_name, reason as message, NULL as attempts
            FROM sentinel_failures
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        activity = []
        for row in c.fetchall():
            activity.append({
                "type": row[0],
                "timestamp": row[1],
                "server_id": row[2],
                "service_name": row[3],
                "message": row[4],
                "attempts": row[5]
            })
        
        conn.close()
        return activity

    def get_health_score(self, server_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        c.execute("""
            SELECT COUNT(*) FROM sentinel_checks 
            WHERE server_id = ? AND timestamp > ?
        """, (server_id, week_ago))
        total_checks = c.fetchone()[0]
        
        if total_checks == 0:
            conn.close()
            return 100
        
        c.execute("""
            SELECT COUNT(*) FROM sentinel_checks 
            WHERE server_id = ? AND timestamp > ? AND status = 'healthy'
        """, (server_id, week_ago))
        healthy_checks = c.fetchone()[0]
        
        c.execute("""
            SELECT COUNT(*) FROM sentinel_repairs 
            WHERE server_id = ? AND timestamp > ? AND success = 0
        """, (server_id, week_ago))
        failed_repairs = c.fetchone()[0]
        
        conn.close()
        
        uptime_score = (healthy_checks / total_checks) * 100
        repair_penalty = min(failed_repairs * 5, 20)
        
        health_score = max(0, uptime_score - repair_penalty)
        return round(health_score, 1)

    def reset_stats(self):
        """Reset all dashboard statistics and metrics"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute("DELETE FROM sentinel_checks")
            checks_deleted = c.rowcount
            
            c.execute("DELETE FROM sentinel_repairs")
            repairs_deleted = c.rowcount
            
            c.execute("DELETE FROM sentinel_failures")
            failures_deleted = c.rowcount
            
            c.execute("DELETE FROM sentinel_metrics")
            metrics_deleted = c.rowcount
            
            c.execute("DELETE FROM sentinel_logs")
            logs_deleted = c.rowcount
            
            conn.commit()
            conn.close()
            
            self._failure_counts = {}
            
            total = checks_deleted + repairs_deleted + failures_deleted + metrics_deleted + logs_deleted
            self.logger(f"[sentinel] Stats reset: {total} records deleted")
            
            return {
                "success": True,
                "deleted": {
                    "checks": checks_deleted,
                    "repairs": repairs_deleted,
                    "failures": failures_deleted,
                    "metrics": metrics_deleted,
                    "logs": logs_deleted,
                    "total": total
                }
            }
        except Exception as e:
            self.logger(f"[sentinel] Error resetting stats: {e}")
            return {"success": False, "error": str(e)}

    def manual_purge(self, days=None, server_id=None, service_name=None, successful_only=False):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        total_deleted = 0
        
        if days is None:
            c.execute("DELETE FROM sentinel_checks")
            total_deleted += c.rowcount
            
            c.execute("DELETE FROM sentinel_repairs")
            total_deleted += c.rowcount
            
            c.execute("DELETE FROM sentinel_failures")
            total_deleted += c.rowcount
            
            c.execute("DELETE FROM sentinel_metrics")
            total_deleted += c.rowcount
            
            c.execute("DELETE FROM sentinel_logs")
            total_deleted += c.rowcount
        else:
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            if server_id:
                c.execute("DELETE FROM sentinel_checks WHERE timestamp < ? AND server_id = ?", 
                         (cutoff_date, server_id))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_repairs WHERE timestamp < ? AND server_id = ?", 
                         (cutoff_date, server_id))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_failures WHERE timestamp < ? AND server_id = ?", 
                         (cutoff_date, server_id))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_logs WHERE timestamp < ? AND server_id = ?", 
                         (cutoff_date, server_id))
                total_deleted += c.rowcount
            
            elif service_name:
                c.execute("DELETE FROM sentinel_checks WHERE timestamp < ? AND service_name = ?", 
                         (cutoff_date, service_name))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_repairs WHERE timestamp < ? AND service_name = ?", 
                         (cutoff_date, service_name))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_failures WHERE timestamp < ? AND service_name = ?", 
                         (cutoff_date, service_name))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_logs WHERE timestamp < ? AND service_name = ?", 
                         (cutoff_date, service_name))
                total_deleted += c.rowcount
            
            elif successful_only:
                c.execute("DELETE FROM sentinel_checks WHERE timestamp < ? AND status = 'healthy'", 
                         (cutoff_date,))
                total_deleted += c.rowcount
            
            else:
                c.execute("DELETE FROM sentinel_checks WHERE timestamp < ?", (cutoff_date,))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_repairs WHERE timestamp < ?", (cutoff_date,))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_failures WHERE timestamp < ?", (cutoff_date,))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_metrics WHERE timestamp < ?", (cutoff_date,))
                total_deleted += c.rowcount
                
                c.execute("DELETE FROM sentinel_logs WHERE timestamp < ?", (cutoff_date,))
                total_deleted += c.rowcount
        
        conn.commit()
        conn.close()
        
        return {"success": True, "deleted": total_deleted}

    async def auto_purge(self):
        while True:
            try:
                await asyncio.sleep(86400)
                
                cutoff_date = (datetime.now() - timedelta(days=90)).isoformat()
                
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                
                c.execute("DELETE FROM sentinel_checks WHERE timestamp < ?", (cutoff_date,))
                checks_deleted = c.rowcount
                
                c.execute("DELETE FROM sentinel_repairs WHERE timestamp < ?", (cutoff_date,))
                repairs_deleted = c.rowcount
                
                c.execute("DELETE FROM sentinel_failures WHERE timestamp < ?", (cutoff_date,))
                failures_deleted = c.rowcount
                
                c.execute("DELETE FROM sentinel_metrics WHERE timestamp < ?", (cutoff_date,))
                metrics_deleted = c.rowcount
                
                c.execute("DELETE FROM sentinel_logs WHERE timestamp < ?", (cutoff_date,))
                logs_deleted = c.rowcount
                
                conn.commit()
                conn.close()
                
                self.logger(f"Auto-purge completed: {checks_deleted} checks, {repairs_deleted} repairs, {failures_deleted} failures, {metrics_deleted} metrics, {logs_deleted} logs deleted")
                
            except Exception as e:
                self.logger(f"Error in auto-purge: {e}")

    def setup_routes(self, app):
        app.router.add_get("/api/sentinel/servers", self.api_get_servers)
        app.router.add_post("/api/sentinel/servers", self.api_add_server)
        app.router.add_put("/api/sentinel/servers/{server_id}", self.api_update_server)
        app.router.add_delete("/api/sentinel/servers/{server_id}", self.api_delete_server)
        
        app.router.add_get("/api/sentinel/templates", self.api_get_templates)
        app.router.add_get("/api/sentinel/templates/{filename}", self.api_download_template)
        app.router.add_post("/api/sentinel/templates", self.api_upload_template)
        app.router.add_put("/api/sentinel/templates/{filename}", self.api_update_template)
        app.router.add_delete("/api/sentinel/templates/{filename}", self.api_delete_template)
        app.router.add_post("/api/sentinel/templates/sync", self.api_sync_templates)
        
        app.router.add_get("/api/sentinel/settings", self.api_get_settings)
        app.router.add_put("/api/sentinel/settings", self.api_update_settings)
        
        app.router.add_get("/api/sentinel/monitoring", self.api_get_monitoring)
        app.router.add_post("/api/sentinel/monitoring", self.api_add_monitoring)
        app.router.add_put("/api/sentinel/monitoring/{server_id}", self.api_update_monitoring)
        app.router.add_delete("/api/sentinel/monitoring/{server_id}", self.api_delete_monitoring)
        app.router.add_post("/api/sentinel/monitoring/{server_id}/disable/{service_id}", self.api_disable_service)
        
        app.router.add_get("/api/sentinel/maintenance", self.api_get_maintenance)
        app.router.add_post("/api/sentinel/maintenance", self.api_add_maintenance)
        app.router.add_put("/api/sentinel/maintenance/{window_id}", self.api_update_maintenance)
        app.router.add_delete("/api/sentinel/maintenance/{window_id}", self.api_delete_maintenance)
        
        app.router.add_get("/api/sentinel/quiet-hours", self.api_get_quiet_hours)
        app.router.add_put("/api/sentinel/quiet-hours", self.api_update_quiet_hours)
        
        app.router.add_get("/api/sentinel/dashboard", self.api_dashboard)
        app.router.add_get("/api/sentinel/status", self.api_live_status)
        app.router.add_get("/api/sentinel/activity", self.api_recent_activity)
        app.router.add_get("/api/sentinel/health/{server_id}", self.api_health_score)
        
        app.router.add_get("/api/sentinel/logs/stream", self.api_log_stream)
        app.router.add_get("/api/sentinel/logs/history", self.api_log_history)
        app.router.add_get("/api/sentinel/logs/execution/{execution_id}", self.api_execution_logs)
        app.router.add_delete("/api/sentinel/logs/{execution_id}", self.api_delete_logs)
        
        app.router.add_post("/api/sentinel/test/check", self.api_manual_check)
        app.router.add_post("/api/sentinel/test/repair", self.api_manual_repair)
        
        app.router.add_post("/api/sentinel/start/{server_id}", self.api_start_monitoring)
        app.router.add_post("/api/sentinel/stop/{server_id}", self.api_stop_monitoring)
        app.router.add_post("/api/sentinel/start-all", self.api_start_all)
        
        app.router.add_post("/api/sentinel/purge", self.api_manual_purge)
        app.router.add_post("/api/sentinel/reset-stats", self.api_reset_stats)

    # API Handlers
    
    async def api_get_servers(self, request):
        servers = self.load_servers()
        return web.json_response({"servers": servers})

    async def api_add_server(self, request):
        data = await request.json()
        result = self.add_server(
            data["id"],
            data["host"],
            data.get("port", 22),
            data["username"],
            data["password"],
            data.get("description", "")
        )
        return web.json_response(result)

    async def api_update_server(self, request):
        server_id = request.match_info["server_id"]
        data = await request.json()
        result = self.update_server(server_id, data)
        return web.json_response(result)

    async def api_delete_server(self, request):
        server_id = request.match_info["server_id"]
        result = self.delete_server(server_id)
        return web.json_response(result)

    async def api_get_templates(self, request):
        templates = self.load_templates()
        return web.json_response({"templates": templates})

    async def api_download_template(self, request):
        filename = request.match_info["filename"]
        result = self.download_template(filename)
        if result["success"]:
            return web.Response(text=result["content"], content_type="text/plain")
        return web.json_response(result, status=404)

    async def api_upload_template(self, request):
        data = await request.json()
        result = self.upload_template(data["content"], data["filename"])
        return web.json_response(result)

    async def api_update_template(self, request):
        filename = request.match_info["filename"]
        data = await request.json()
        result = self.save_template(data, filename)
        return web.json_response(result)

    async def api_delete_template(self, request):
        filename = request.match_info["filename"]
        result = self.delete_template(filename)
        return web.json_response(result)

    async def api_sync_templates(self, request):
        try:
            data = await request.json()
            custom_url = data.get("url")
        except:
            custom_url = None
        
        result = await self.sync_github_templates(custom_url)
        return web.json_response(result)

    async def api_get_settings(self, request):
        settings = self.load_settings()
        return web.json_response(settings)

    async def api_update_settings(self, request):
        data = await request.json()
        if self.save_settings(data):
            return web.json_response({"success": True})
        return web.json_response({"success": False, "error": "Failed to save settings"})

    async def api_get_monitoring(self, request):
        monitoring = self.load_monitoring()
        return web.json_response({"monitoring": monitoring})

    async def api_add_monitoring(self, request):
        data = await request.json()
        result = self.add_monitoring(
            data["server_id"],
            data["services"],
            data.get("check_interval", 300),
            data.get("service_intervals", {})
        )
        return web.json_response(result)

    async def api_update_monitoring(self, request):
        server_id = request.match_info["server_id"]
        data = await request.json()
        result = self.update_monitoring(server_id, data)
        return web.json_response(result)

    async def api_delete_monitoring(self, request):
        server_id = request.match_info["server_id"]
        result = self.delete_monitoring(server_id)
        return web.json_response(result)

    async def api_disable_service(self, request):
        server_id = request.match_info["server_id"]
        service_id = request.match_info["service_id"]
        data = await request.json()
        duration = data.get("duration_hours", 2)
        result = self.disable_service_temporarily(server_id, service_id, duration)
        return web.json_response(result)

    async def api_get_maintenance(self, request):
        windows = self.load_maintenance_windows()
        return web.json_response({"windows": windows})

    async def api_add_maintenance(self, request):
        data = await request.json()
        windows = self.load_maintenance_windows()
        windows.append(data)
        self.save_maintenance_windows(windows)
        return web.json_response({"success": True})

    async def api_update_maintenance(self, request):
        window_id = int(request.match_info["window_id"])
        data = await request.json()
        windows = self.load_maintenance_windows()
        if 0 <= window_id < len(windows):
            windows[window_id] = data
            self.save_maintenance_windows(windows)
            return web.json_response({"success": True})
        return web.json_response({"success": False, "error": "Window not found"}, status=404)

    async def api_delete_maintenance(self, request):
        window_id = int(request.match_info["window_id"])
        windows = self.load_maintenance_windows()
        if 0 <= window_id < len(windows):
            windows.pop(window_id)
            self.save_maintenance_windows(windows)
            return web.json_response({"success": True})
        return web.json_response({"success": False, "error": "Window not found"}, status=404)

    async def api_get_quiet_hours(self, request):
        config = self.load_quiet_hours()
        return web.json_response(config)

    async def api_update_quiet_hours(self, request):
        data = await request.json()
        filepath = os.path.join(self.data_path, "quiet_hours.json")
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return web.json_response({"success": True})

    async def api_dashboard(self, request):
        metrics = self.get_dashboard_metrics()
        return web.json_response(metrics)

    async def api_live_status(self, request):
        status = self.get_live_status()
        return web.json_response({"status": status})

    async def api_recent_activity(self, request):
        limit = int(request.query.get("limit", 20))
        activity = self.get_recent_activity(limit)
        return web.json_response({"activity": activity})

    async def api_health_score(self, request):
        server_id = request.match_info["server_id"]
        score = self.get_health_score(server_id)
        return web.json_response({"server_id": server_id, "health_score": score})

    async def api_log_stream(self, request):
        execution_id = request.query.get("execution_id")
        if not execution_id:
            return web.json_response({"error": "execution_id required"}, status=400)
        
        resp = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
            }
        )
        await resp.prepare(request)
        
        q = asyncio.Queue(maxsize=200)
        
        if execution_id not in self._log_listeners:
            self._log_listeners[execution_id] = set()
        self._log_listeners[execution_id].add(q)
        
        try:
            await resp.write(b": connected\n\n")
        except Exception:
            pass
        
        try:
            while True:
                data = await q.get()
                payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
                try:
                    await resp.write(b"data: " + payload + b"\n\n")
                    
                    if data.get("type") == "complete":
                        await asyncio.sleep(1)
                        break
                        
                except (ConnectionResetError, RuntimeError, BrokenPipeError):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if execution_id in self._log_listeners:
                self._log_listeners[execution_id].discard(q)
                if not self._log_listeners[execution_id]:
                    del self._log_listeners[execution_id]
            try:
                await resp.write_eof()
            except Exception:
                pass
        
        return resp
    
    async def api_log_history(self, request):
        server_id = request.query.get("server_id")
        service_name = request.query.get("service_name")
        limit = int(request.query.get("limit", 50))
        manual_only = request.query.get("manual_only") == "true"
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        query = "SELECT execution_id, timestamp, server_id, service_name, action, exit_code, manual_trigger FROM sentinel_logs WHERE 1=1"
        params = []
        
        if server_id:
            query += " AND server_id = ?"
            params.append(server_id)
        
        if service_name:
            query += " AND service_name = ?"
            params.append(service_name)
        
        if manual_only:
            query += " AND manual_trigger = 1"
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        c.execute(query, params)
        
        executions = {}
        for row in c.fetchall():
            exec_id = row[0]
            if exec_id not in executions:
                executions[exec_id] = {
                    "execution_id": exec_id,
                    "timestamp": row[1],
                    "server_id": row[2],
                    "service_name": row[3],
                    "actions": [],
                    "manual": bool(row[6])
                }
            executions[exec_id]["actions"].append({
                "action": row[4],
                "exit_code": row[5]
            })
        
        conn.close()
        
        return web.json_response({"executions": list(executions.values())})
    
    async def api_execution_logs(self, request):
        execution_id = request.match_info["execution_id"]
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            SELECT timestamp, server_id, service_name, action, command, output, exit_code, manual_trigger
            FROM sentinel_logs
            WHERE execution_id = ?
            ORDER BY timestamp ASC
        """, (execution_id,))
        
        logs = []
        for row in c.fetchall():
            logs.append({
                "timestamp": row[0],
                "server_id": row[1],
                "service_name": row[2],
                "action": row[3],
                "command": row[4],
                "output": row[5],
                "exit_code": row[6],
                "manual": bool(row[7])
            })
        
        conn.close()
        
        if not logs:
            return web.json_response({"error": "Execution not found"}, status=404)
        
        return web.json_response({"execution_id": execution_id, "logs": logs})

    async def api_delete_logs(self, request):
        execution_id = request.match_info["execution_id"]
        
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("DELETE FROM sentinel_logs WHERE execution_id = ?", (execution_id,))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            
            return web.json_response({"success": True, "deleted": deleted})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)
    
    async def api_manual_check(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "bad json"}, status=400)
        
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
        
        execution_id = f"manual_{server_id}_{service_id}_{int(datetime.now().timestamp())}"
        asyncio.create_task(self.check_service(server, template, execution_id=execution_id, manual=True))
        
        return web.json_response({
            "execution_id": execution_id,
            "stream_url": f"/api/sentinel/logs/stream?execution_id={execution_id}"
        })
    
    async def api_manual_repair(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "bad json"}, status=400)
        
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
