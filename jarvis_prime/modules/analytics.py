"""
Jarvis Prime - Analytics & Uptime Monitoring Module
aiohttp-compatible version for Jarvis Prime
"""

import sqlite3
import time
import json
import asyncio
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
    check_type: str  # 'http' or 'tcp'
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
    
    def get_health_score(self) -> Dict:
        """Calculate overall homelab health score"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (24 * 3600)
        
        # Get all services and their current status
        cur.execute("""
            SELECT DISTINCT service_name,
                (SELECT status FROM analytics_metrics m 
                 WHERE m.service_name = analytics_metrics.service_name 
                 ORDER BY timestamp DESC LIMIT 1) as current_status
            FROM analytics_metrics
            WHERE timestamp > ?
        """, (cutoff,))
        
        services = cur.fetchall()
        total_services = len(services)
        up_services = sum(1 for s in services if s[1] == 'up')
        down_services = sum(1 for s in services if s[1] == 'down')
        
        # Calculate average uptime
        cur.execute("""
            SELECT AVG(CASE WHEN status = 'up' THEN 1.0 ELSE 0.0 END) * 100
            FROM analytics_metrics
            WHERE timestamp > ?
        """, (cutoff,))
        
        avg_uptime = cur.fetchone()[0] or 0
        
        conn.close()
        
        # Determine status
        if avg_uptime >= 99:
            status = "excellent"
        elif avg_uptime >= 95:
            status = "good"
        elif avg_uptime >= 90:
            status = "fair"
        else:
            status = "poor"
        
        return {
            "health_score": round(avg_uptime, 2),
            "status": status,
            "total_services": total_services,
            "up_services": up_services,
            "down_services": down_services
        }
    
    def create_incident(self, service_name: str, error_message: str) -> int:
        """Create a new incident"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Check if there's already an ongoing incident
        cur.execute("""
            SELECT id FROM analytics_incidents 
            WHERE service_name = ? AND status = 'ongoing'
            ORDER BY start_time DESC LIMIT 1
        """, (service_name,))
        
        existing = cur.fetchone()
        if existing:
            conn.close()
            return existing[0]
        
        # Create new incident
        cur.execute("""
            INSERT INTO analytics_incidents (service_name, start_time, error_message)
            VALUES (?, ?, ?)
        """, (service_name, int(time.time()), error_message))
        
        incident_id = cur.lastrowid
        conn.commit()
        conn.close()
        
        return incident_id
    
    def resolve_incident(self, service_name: str):
        """Resolve an ongoing incident"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        now = int(time.time())
        
        cur.execute("""
            UPDATE analytics_incidents 
            SET end_time = ?,
                duration = ? - start_time,
                status = 'resolved'
            WHERE service_name = ? AND status = 'ongoing'
        """, (now, now, service_name))
        
        conn.commit()
        conn.close()
    
    def get_recent_incidents(self, days: int = 7) -> List[Dict]:
        """Get recent incidents"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (days * 24 * 3600)
        
        cur.execute("""
            SELECT * FROM analytics_incidents
            WHERE start_time > ?
            ORDER BY start_time DESC
            LIMIT 50
        """, (cutoff,))
        
        incidents = [dict(row) for row in cur.fetchall()]
        conn.close()
        return incidents


class HealthMonitor:
    """Performs health checks on services"""
    
    def __init__(self, db: AnalyticsDB):
        self.db = db
        self.session = None
        self.monitoring_tasks = {}
        self.previous_status = {}
    
    async def init_session(self):
        """Initialize aiohttp session"""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close_session(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()
    
    async def check_http(self, service: HealthCheck) -> ServiceMetric:
        """Perform HTTP health check"""
        start_time = time.time()
        
        try:
            async with self.session.get(
                service.endpoint,
                timeout=aiohttp.ClientTimeout(total=service.timeout)
            ) as resp:
                response_time = time.time() - start_time
                
                if resp.status == service.expected_status:
                    status = 'up'
                    error = None
                else:
                    status = 'degraded'
                    error = f"HTTP {resp.status}"
                
                return ServiceMetric(
                    service_name=service.service_name,
                    timestamp=int(time.time()),
                    status=status,
                    response_time=response_time,
                    error_message=error
                )
        
        except asyncio.TimeoutError:
            return ServiceMetric(
                service_name=service.service_name,
                timestamp=int(time.time()),
                status='down',
                response_time=time.time() - start_time,
                error_message="Timeout"
            )
        except Exception as e:
            return ServiceMetric(
                service_name=service.service_name,
                timestamp=int(time.time()),
                status='down',
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    async def check_tcp(self, service: HealthCheck) -> ServiceMetric:
        """Perform TCP port check"""
        start_time = time.time()
        
        try:
            host, port = service.endpoint.split(":")
            port = int(port)
        except ValueError:
            return ServiceMetric(
                service_name=service.service_name,
                timestamp=int(time.time()),
                status='down',
                response_time=0,
                error_message="Invalid endpoint format"
            )
        
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=service.timeout
            )
            writer.close()
            await writer.wait_closed()
            
            return ServiceMetric(
                service_name=service.service_name,
                timestamp=int(time.time()),
                status='up',
                response_time=time.time() - start_time,
                error_message=None
            )
        
        except Exception as e:
            return ServiceMetric(
                service_name=service.service_name,
                timestamp=int(time.time()),
                status='down',
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    async def perform_check(self, service: HealthCheck) -> ServiceMetric:
        """Perform appropriate health check"""
        if service.check_type == 'http':
            return await self.check_http(service)
        elif service.check_type == 'tcp':
            return await self.check_tcp(service)
        else:
            return ServiceMetric(
                service_name=service.service_name,
                timestamp=int(time.time()),
                status='unknown',
                response_time=0,
                error_message=f"Unknown check type: {service.check_type}"
            )
    
    async def monitor_service(self, service: HealthCheck):
        """Continuously monitor a single service"""
        logger.info(f"Starting monitor for {service.service_name}")
        
        while True:
            try:
                if not service.enabled:
                    await asyncio.sleep(service.interval)
                    continue
                
                # Perform health check
                metric = await self.perform_check(service)
                self.db.record_metric(metric)
                
                # Incident detection
                prev_status = self.previous_status.get(service.service_name)
                
                if metric.status == 'down' and prev_status != 'down':
                    self.db.create_incident(service.service_name, metric.error_message)
                    logger.warning(f"{service.service_name} is DOWN: {metric.error_message}")
                    
                elif metric.status == 'up' and prev_status == 'down':
                    self.db.resolve_incident(service.service_name)
                    logger.info(f"{service.service_name} is back UP")
                
                self.previous_status[service.service_name] = metric.status
                
            except Exception as e:
                logger.error(f"Error monitoring {service.service_name}: {e}")
            
            await asyncio.sleep(service.interval)
    
    async def start_all_monitors(self):
        """Start monitoring all enabled services"""
        await self.init_session()
        
        services = self.db.get_all_services()
        
        for svc_dict in services:
            if svc_dict['enabled']:
                service = HealthCheck(
                    service_name=svc_dict['service_name'],
                    endpoint=svc_dict['endpoint'],
                    check_type=svc_dict['check_type'],
                    expected_status=svc_dict['expected_status'],
                    timeout=svc_dict['timeout'],
                    interval=svc_dict['check_interval'],
                    enabled=bool(svc_dict['enabled'])
                )
                
                task = asyncio.create_task(self.monitor_service(service))
                self.monitoring_tasks[service.service_name] = task
        
        logger.info(f"Started {len(self.monitoring_tasks)} monitoring tasks")


# ============================================
# API Routes (aiohttp)
# ============================================

# Global instances
db = None
monitor = None


def init_analytics(db_path: str = "/data/jarvis.db"):
    """Initialize analytics module"""
    global db, monitor
    db = AnalyticsDB(db_path)
    monitor = HealthMonitor(db)
    return db, monitor


def _json(data, status=200):
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json"
    )


async def get_health_score(request: web.Request):
    """Get overall health score"""
    score = db.get_health_score()
    return _json(score)


async def get_services(request: web.Request):
    """Get all monitored services"""
    services = db.get_all_services()
    return _json(services)


async def add_service(request: web.Request):
    """Add a new service"""
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    service = HealthCheck(
        service_name=data['service_name'],
        endpoint=data['endpoint'],
        check_type=data['check_type'],
        expected_status=data.get('expected_status', 200),
        timeout=data.get('timeout', 5),
        interval=data.get('check_interval', 60),
        enabled=data.get('enabled', True)
    )
    
    service_id = db.add_service(service)
    
    if service.enabled and monitor:
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({"success": True, "service_id": int(service_id)})


async def get_service(request: web.Request):
    """Get a single service"""
    service_id = int(request.match_info["service_id"])
    service = db.get_service(service_id)
    if service:
        return _json(service)
    return _json({"error": "Service not found"}, status=404)


async def update_service(request: web.Request):
    """Update a service"""
    service_id = int(request.match_info["service_id"])
    
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    service = HealthCheck(
        service_name=data['service_name'],
        endpoint=data['endpoint'],
        check_type=data['check_type'],
        expected_status=data.get('expected_status', 200),
        timeout=data.get('timeout', 5),
        interval=data.get('check_interval', 60),
        enabled=data.get('enabled', True)
    )
    
    db.add_service(service)
    
    if service.enabled and monitor:
        if service.service_name in monitor.monitoring_tasks:
            monitor.monitoring_tasks[service.service_name].cancel()
        
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({"success": True})


async def delete_service_route(request: web.Request):
    """Delete a service"""
    service_id = int(request.match_info["service_id"])
    
    service = db.get_service(service_id)
    if service and monitor:
        service_name = service['service_name']
        if service_name in monitor.monitoring_tasks:
            monitor.monitoring_tasks[service_name].cancel()
            del monitor.monitoring_tasks[service_name]
    
    db.delete_service(service_id)
    return _json({"success": True})


async def get_uptime(request: web.Request):
    """Get uptime stats for a service"""
    service_name = request.match_info["service_name"]
    hours = int(request.rel_url.query.get('hours', 24))
    
    stats = db.get_uptime_stats(service_name, hours)
    if stats:
        return _json(stats)
    return _json({"error": "No data found"}, status=404)


async def get_incidents(request: web.Request):
    """Get recent incidents"""
    days = int(request.rel_url.query.get('days', 7))
    incidents = db.get_recent_incidents(days)
    return _json(incidents)


def register_routes(app: web.Application):
    """Register analytics routes with aiohttp app"""
    app.router.add_get('/api/analytics/health-score', get_health_score)
    app.router.add_get('/api/analytics/services', get_services)
    app.router.add_post('/api/analytics/services', add_service)
    app.router.add_get('/api/analytics/services/{service_id}', get_service)
    app.router.add_put('/api/analytics/services/{service_id}', update_service)
    app.router.add_delete('/api/analytics/services/{service_id}', delete_service_route)
    app.router.add_get('/api/analytics/uptime/{service_name}', get_uptime)
    app.router.add_get('/api/analytics/incidents', get_incidents)
