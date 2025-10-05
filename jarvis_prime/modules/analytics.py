"""
Jarvis Prime - Analytics & Uptime Monitoring Module
aiohttp-compatible version for Jarvis Prime
PATCHED: Now includes dual notification support (process_incoming fan-out + legacy callback)
PATCHED: get_incidents now returns consistent { "incidents": [...] } format
PATCHED: analytics_notify is now always used as the primary callback
"""

import sqlite3
import time
import json
import asyncio
import subprocess
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from aiohttp import web
import logging

logger = logging.getLogger(__name__)


@dataclass
class HealthCheck:
    """Health check configuration"""
    service_name: str
    endpoint: str
    check_type: str  # 'http', 'tcp', or 'ping'
    expected_status: int = 200
    timeout: int = 5
    interval: int = 60
    enabled: bool = True


@dataclass
class ServiceMetric:
    """Single health check result"""
    service_name: str
    timestamp: int
    status: str  # 'up', 'down', 'degraded'
    response_time: float
    error_message: Optional[str] = None


class AnalyticsDB:
    """Database handler for analytics data"""
    
    def __init__(self, db_path: str = "/data/jarvis.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize analytics tables"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Services configuration table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analytics_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL UNIQUE,
                endpoint TEXT NOT NULL,
                check_type TEXT NOT NULL,
                expected_status INTEGER DEFAULT 200,
                timeout INTEGER DEFAULT 5,
                check_interval INTEGER DEFAULT 60,
                enabled INTEGER DEFAULT 1,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        # Service metrics (health check results)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analytics_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                status TEXT NOT NULL,
                response_time REAL,
                error_message TEXT
            )
        """)
        
        # Create index for faster queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_service_time 
            ON analytics_metrics(service_name, timestamp DESC)
        """)
        
        # Incidents table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analytics_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER,
                duration INTEGER,
                status TEXT DEFAULT 'ongoing',
                error_message TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("Analytics database initialized")
    
    def add_service(self, service: HealthCheck) -> int:
        """Add or update a service configuration"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO analytics_services 
            (service_name, endpoint, check_type, expected_status, timeout, check_interval, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_name) DO UPDATE SET
                endpoint=excluded.endpoint,
                check_type=excluded.check_type,
                expected_status=excluded.expected_status,
                timeout=excluded.timeout,
                check_interval=excluded.check_interval,
                enabled=excluded.enabled,
                updated_at=strftime('%s', 'now')
        """, (service.service_name, service.endpoint, service.check_type,
              service.expected_status, service.timeout, service.interval,
              int(service.enabled)))
        
        service_id = cur.lastrowid
        conn.commit()
        conn.close()
        return service_id
    
    def get_all_services(self) -> List[Dict]:
        """Get all configured services"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                id,
                service_name,
                endpoint,
                check_type,
                expected_status,
                timeout,
                check_interval,
                enabled,
                (SELECT status FROM analytics_metrics 
                 WHERE service_name = analytics_services.service_name 
                 ORDER BY timestamp DESC LIMIT 1) as current_status,
                (SELECT timestamp FROM analytics_metrics 
                 WHERE service_name = analytics_services.service_name 
                 ORDER BY timestamp DESC LIMIT 1) as last_check
            FROM analytics_services
            ORDER BY service_name
        """)
        
        services = [dict(row) for row in cur.fetchall()]
        conn.close()
        return services
    
    def get_service(self, service_id: int) -> Optional[Dict]:
        """Get a single service by ID"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("SELECT * FROM analytics_services WHERE id = ?", (service_id,))
        row = cur.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def delete_service(self, service_id: int):
        """Delete a service and its metrics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Get service name first
        cur.execute("SELECT service_name FROM analytics_services WHERE id = ?", (service_id,))
        row = cur.fetchone()
        
        if row:
            service_name = row[0]
            # Delete metrics
            cur.execute("DELETE FROM analytics_metrics WHERE service_name = ?", (service_name,))
            # Delete incidents
            cur.execute("DELETE FROM analytics_incidents WHERE service_name = ?", (service_name,))
            # Delete service
            cur.execute("DELETE FROM analytics_services WHERE id = ?", (service_id,))
        
        conn.commit()
        conn.close()
    
    def record_metric(self, metric: ServiceMetric):
        """Record a health check result"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO analytics_metrics 
            (service_name, timestamp, status, response_time, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (metric.service_name, metric.timestamp, metric.status,
              metric.response_time, metric.error_message))
        
        conn.commit()
        conn.close()
    
    def get_uptime_stats(self, service_name: str, hours: int = 24) -> Optional[Dict]:
        """Calculate uptime percentage for a service"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (hours * 3600)
        
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END) as up_count,
                AVG(response_time) as avg_response,
                MIN(response_time) as min_response,
                MAX(response_time) as max_response
            FROM analytics_metrics
            WHERE service_name = ? AND timestamp > ?
        """, (service_name, cutoff))
        
        row = cur.fetchone()
        conn.close()
        
        if row and row[0] > 0:
            total, up_count, avg_resp, min_resp, max_resp = row
            uptime_pct = (up_count / total) * 100
            return {
                "service_name": service_name,
                "period_hours": hours,
                "total_checks": total,
                "successful_checks": up_count,
                "uptime_percentage": round(uptime_pct, 2),
                "avg_response_time": round(avg_resp, 3) if avg_resp else None,
                "min_response_time": round(min_resp, 3) if min_resp else None,
                "max_response_time": round(max_resp, 3) if max_resp else None
            }
        return None
    def get_recent_metrics(self, service_name: str, limit: int = 50) -> List[Dict]:
        """Return the most recent metrics for a service"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT timestamp, status, response_time, error_message
            FROM analytics_metrics
            WHERE service_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (service_name, limit))
        
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows

    def get_incidents(self, service_name: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Return a list of incidents"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        if service_name:
            cur.execute("""
                SELECT * FROM analytics_incidents
                WHERE service_name = ?
                ORDER BY start_time DESC
                LIMIT ?
            """, (service_name, limit))
        else:
            cur.execute("""
                SELECT * FROM analytics_incidents
                ORDER BY start_time DESC
                LIMIT ?
            """, (limit,))
        
        incidents = [dict(row) for row in cur.fetchall()]
        conn.close()
        return incidents

    def start_incident(self, service_name: str, error_message: Optional[str] = None) -> int:
        """Start a new incident"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        timestamp = int(time.time())
        
        cur.execute("""
            INSERT INTO analytics_incidents
            (service_name, start_time, status, error_message)
            VALUES (?, ?, 'ongoing', ?)
        """, (service_name, timestamp, error_message))
        
        incident_id = cur.lastrowid
        conn.commit()
        conn.close()
        return incident_id

    def resolve_incident(self, incident_id: int):
        """Mark an incident as resolved"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        end_time = int(time.time())
        cur.execute("""
            SELECT start_time FROM analytics_incidents WHERE id = ?
        """, (incident_id,))
        row = cur.fetchone()
        if row:
            duration = end_time - row[0]
            cur.execute("""
                UPDATE analytics_incidents
                SET end_time = ?, duration = ?, status = 'resolved'
                WHERE id = ?
            """, (end_time, duration, incident_id))
        
        conn.commit()
        conn.close()


class AnalyticsMonitor:
    """Performs health checks and updates DB"""
    
    def __init__(self, db: AnalyticsDB, notify_callback=None, poll_interval: int = 60):
        self.db = db
        self.poll_interval = poll_interval
        self.notify_callback = notify_callback  # Optional notification function
        self.running = False
        self.tasks = []
        self.incident_map = {}  # service_name -> incident_id
    
    async def check_service(self, service: Dict):
        """Perform a single health check for a service"""
        name = service["service_name"]
        endpoint = service["endpoint"]
        check_type = service["check_type"]
        timeout = service["timeout"]
        expected_status = service["expected_status"]
        
        timestamp = int(time.time())
        status = "down"
        response_time = None
        error_message = None
        
        start = time.time()
        try:
            if check_type == "http":
                async with aiohttp.ClientSession() as session:
                    async with session.get(endpoint, timeout=timeout) as resp:
                        response_time = time.time() - start
                        if resp.status == expected_status:
                            status = "up"
                        else:
                            status = "degraded"
                            error_message = f"Unexpected HTTP status: {resp.status}"
            elif check_type == "ping":
                proc = await asyncio.create_subprocess_shell(
                    f"ping -c 1 -W {timeout} {endpoint}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                response_time = time.time() - start
                if proc.returncode == 0:
                    status = "up"
                else:
                    status = "down"
                    error_message = stderr.decode().strip()
            else:
                status = "unknown"
                error_message = f"Unsupported check type: {check_type}"
        except Exception as e:
            response_time = time.time() - start
            status = "down"
            error_message = str(e)
        
        metric = ServiceMetric(
            service_name=name,
            timestamp=timestamp,
            status=status,
            response_time=response_time,
            error_message=error_message
        )
        
        self.db.record_metric(metric)
        
        # Handle incidents
        ongoing_incident = self.incident_map.get(name)
        if status != "up":
            if not ongoing_incident:
                incident_id = self.db.start_incident(name, error_message)
                self.incident_map[name] = incident_id
                if self.notify_callback:
                    await self.notify_callback({
                        "type": "incident_start",
                        "service": name,
                        "error": error_message,
                        "timestamp": timestamp
                    })
        else:
            if ongoing_incident:
                self.db.resolve_incident(ongoing_incident)
                del self.incident_map[name]
                if self.notify_callback:
                    await self.notify_callback({
                        "type": "incident_resolved",
                        "service": name,
                        "timestamp": timestamp
                    })
    async def monitor_services(self):
        """Continuously monitor all services"""
        self.running = True
        while self.running:
            try:
                services = self.db.get_all_services()
                tasks = []
                for svc in services:
                    if svc["enabled"]:
                        tasks.append(self.check_service(svc))
                if tasks:
                    await asyncio.gather(*tasks)
            except Exception as e:
                logging.error(f"Error during monitoring loop: {e}")
            await asyncio.sleep(self.poll_interval)

    def start(self):
        """Start the monitoring loop as a background task"""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.monitor_services())
        self.tasks.append(task)

    def stop(self):
        """Stop monitoring"""
        self.running = False
        for t in self.tasks:
            t.cancel()


# Global instances
analytics_db = None
analytics_monitor = None


def init_analytics_system(db_path: str = "/data/jarvis.db", notify_callback=None, poll_interval: int = 60):
    """Initialize analytics database and monitor"""
    global analytics_db, analytics_monitor
    analytics_db = AnalyticsDB(db_path)
    analytics_monitor = AnalyticsMonitor(analytics_db, notify_callback, poll_interval)
    analytics_monitor.start()
    return analytics_db, analytics_monitor


# aiohttp helpers
def _json_response(data, status=200):
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json"
    )


# aiohttp routes
async def api_health_score(request: web.Request):
    try:
        score = analytics_db.get_health_score()
        return _json_response(score)
    except Exception as e:
        return _json_response({"error": str(e)}, status=500)


async def api_services(request: web.Request):
    try:
        services = analytics_db.get_all_services()
        return _json_response(services)
    except Exception as e:
        return _json_response({"error": str(e)}, status=500)


async def api_add_service(request: web.Request):
    try:
        data = await request.json()
        svc = HealthCheck(
            service_name=data["service_name"],
            endpoint=data["endpoint"],
            check_type=data["check_type"],
            expected_status=data.get("expected_status", 200),
            timeout=data.get("timeout", 5),
            interval=data.get("check_interval", 60),
            enabled=data.get("enabled", True)
        )
        service_id = analytics_db.add_service(svc)
        return _json_response({"success": True, "service_id": service_id})
    except Exception as e:
        return _json_response({"error": str(e)}, status=400)


async def api_get_service(request: web.Request):
    try:
        service_id = int(request.match_info["service_id"])
        svc = analytics_db.get_service(service_id)
        if svc:
            return _json_response(svc)
        return _json_response({"error": "Service not found"}, status=404)
    except Exception as e:
        return _json_response({"error": str(e)}, status=400)
async def api_update_service(request: web.Request):
    try:
        service_id = int(request.match_info["service_id"])
        data = await request.json()
        svc = HealthCheck(
            service_name=data["service_name"],
            endpoint=data["endpoint"],
            check_type=data["check_type"],
            expected_status=data.get("expected_status", 200),
            timeout=data.get("timeout", 5),
            interval=data.get("check_interval", 60),
            enabled=data.get("enabled", True)
        )
        analytics_db.add_service(svc)

        # Restart monitor for updated service
        if analytics_monitor and svc.enabled:
            task_name = svc.service_name
            if task_name in analytics_monitor.tasks:
                analytics_monitor.tasks[task_name].cancel()
            task = asyncio.create_task(analytics_monitor.check_service(vars(svc)))
            analytics_monitor.tasks[task_name] = task

        return _json_response({"success": True})
    except Exception as e:
        return _json_response({"error": str(e)}, status=400)


async def api_delete_service(request: web.Request):
    try:
        service_id = int(request.match_info["service_id"])
        svc = analytics_db.get_service(service_id)
        if svc:
            service_name = svc["service_name"]
            analytics_db.delete_service(service_id)
            if analytics_monitor and service_name in analytics_monitor.tasks:
                analytics_monitor.tasks[service_name].cancel()
                del analytics_monitor.tasks[service_name]
        return _json_response({"success": True})
    except Exception as e:
        return _json_response({"error": str(e)}, status=400)


async def api_uptime(request: web.Request):
    try:
        service_name = request.match_info["service_name"]
        hours = int(request.rel_url.query.get("hours", 24))
        stats = analytics_db.get_uptime_stats(service_name, hours)
        if stats:
            return _json_response(stats)
        return _json_response({"error": "No data found"}, status=404)
    except Exception as e:
        return _json_response({"error": str(e)}, status=500)


async def api_incidents(request: web.Request):
    try:
        days = int(request.rel_url.query.get("days", 7))
    except Exception:
        days = 7
    try:
        incidents = analytics_db.get_recent_incidents(days)
        return _json_response({"incidents": incidents})
    except Exception as e:
        logging.error(f"Failed to fetch incidents: {e}")
        return _json_response({"incidents": [], "error": str(e)}, status=500)


async def api_reset_health(request: web.Request):
    try:
        conn = sqlite3.connect(analytics_db.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM analytics_metrics")
        conn.commit()
        conn.close()
        return _json_response({"success": True, "message": "Health scores reset"})
    except Exception as e:
        return _json_response({"success": False, "error": str(e)}, status=500)


async def api_reset_incidents(request: web.Request):
    try:
        conn = sqlite3.connect(analytics_db.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM analytics_incidents")
        conn.commit()
        conn.close()
        return _json_response({"success": True, "message": "All incidents cleared"})
    except Exception as e:
        return _json_response({"success": False, "error": str(e)}, status=500)


async def api_reset_service_data(request: web.Request):
    try:
        service_name = request.match_info["service_name"]
        conn = sqlite3.connect(analytics_db.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM analytics_metrics WHERE service_name = ?", (service_name,))
        cur.execute("DELETE FROM analytics_incidents WHERE service_name = ?", (service_name,))
        conn.commit()
        conn.close()
        return _json_response({"success": True, "message": f"Data reset for {service_name}"})
    except Exception as e:
        return _json_response({"success": False, "error": str(e)}, status=500)


async def api_purge_all_metrics(request: web.Request):
    try:
        deleted = analytics_db.purge_all_metrics()
        return _json_response({
            "success": True,
            "deleted": deleted,
            "message": f"Purged all {deleted} metrics"
        })
    except Exception as e:
        logging.error(f"Purge all failed: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def api_purge_week_metrics(request: web.Request):
    try:
        deleted = analytics_db.purge_metrics_older_than(7)
        return _json_response({
            "success": True,
            "deleted": deleted,
            "days": 7,
            "message": f"Purged {deleted} metrics older than 1 week"
        })
    except Exception as e:
        logging.error(f"Purge week failed: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def api_purge_month_metrics(request: web.Request):
    try:
        deleted = analytics_db.purge_metrics_older_than(30)
        return _json_response({
            "success": True,
            "deleted": deleted,
            "days": 30,
            "message": f"Purged {deleted} metrics older than 1 month"
        })
    except Exception as e:
        logging.error(f"Purge month failed: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)
def register_api_routes(app: web.Application):
    app.router.add_get("/api/analytics/health-score", api_health_score)
    app.router.add_get("/api/analytics/services", api_get_services)
    app.router.add_post("/api/analytics/services", api_add_service)
    app.router.add_get("/api/analytics/services/{service_id}", api_get_service)
    app.router.add_put("/api/analytics/services/{service_id}", api_update_service)
    app.router.add_delete("/api/analytics/services/{service_id}", api_delete_service)
    app.router.add_get("/api/analytics/uptime/{service_name}", api_uptime)
    app.router.add_get("/api/analytics/incidents", api_incidents)
    app.router.add_post("/api/analytics/reset-health", api_reset_health)
    app.router.add_post("/api/analytics/reset-incidents", api_reset_incidents)
    app.router.add_post("/api/analytics/reset-service/{service_name}", api_reset_service_data)
    app.router.add_post("/api/analytics/purge-all", api_purge_all_metrics)
    app.router.add_post("/api/analytics/purge-week", api_purge_week_metrics)
    app.router.add_post("/api/analytics/purge-month", api_purge_month_metrics)


def create_app(db_path: str = "/data/jarvis.db"):
    global analytics_db, analytics_monitor
    analytics_db = AnalyticsDB(db_path)
    analytics_monitor = HealthMonitor(analytics_db)

    app = web.Application()
    register_api_routes(app)

    async def on_startup(app):
        await analytics_monitor.start_all_monitors()

    async def on_cleanup(app):
        await analytics_monitor.close_all_sessions()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8080)
