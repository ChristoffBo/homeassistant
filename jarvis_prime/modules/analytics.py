#!/usr/bin/env python3
"""
Jarvis Prime Analytics Module
Health monitoring with retries, flap protection, and alerting
"""

import sqlite3
import json
import asyncio
import subprocess
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from aiohttp import web
import logging
from collections import deque

# Import notify_error for alerting
from errors import notify_error

logger = logging.getLogger(__name__)


@dataclass
class HealthCheck:
    """Health check configuration with retry and flap protection"""
    service_name: str
    endpoint: str
    check_type: str  # 'http', 'tcp', or 'ping'
    expected_status: int = 200
    timeout: int = 5
    interval: int = 60
    enabled: bool = True
    retries: int = 3
    flap_window: int = 3600  # seconds (1 hour)
    flap_threshold: int = 5
    suppression_duration: int = 3600  # seconds (1 hour)


@dataclass
class ServiceMetric:
    """Single health check result"""
    service_name: str
    timestamp: int
    status: str  # 'up', 'down', 'degraded'
    response_time: float
    error_message: Optional[str] = None


@dataclass
class FlapTracker:
    """Track flapping behavior for a service"""
    flap_times: deque = field(default_factory=deque)  # timestamps of status changes
    suppressed_until: Optional[float] = None  # timestamp when suppression ends
    last_status: Optional[str] = None  # last known status
    consecutive_failures: int = 0  # track consecutive failures for retries


class AnalyticsDB:
    """Database handler for analytics data"""
    
    def __init__(self, db_path: str = "/data/jarvis.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize analytics tables with new columns"""
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
                retries INTEGER DEFAULT 3,
                flap_window INTEGER DEFAULT 3600,
                flap_threshold INTEGER DEFAULT 5,
                suppression_duration INTEGER DEFAULT 3600,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        # Metrics table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analytics_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                status TEXT NOT NULL,
                response_time REAL,
                error_message TEXT,
                FOREIGN KEY (service_name) REFERENCES analytics_services(service_name)
            )
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_service_time 
            ON analytics_metrics(service_name, timestamp DESC)
        """)
        
        # Incidents table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analytics_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                incident_start INTEGER NOT NULL,
                incident_end INTEGER,
                status TEXT NOT NULL,
                error_message TEXT,
                FOREIGN KEY (service_name) REFERENCES analytics_services(service_name)
            )
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_service_time 
            ON analytics_incidents(service_name, incident_start DESC)
        """)
        
        # Migrate existing tables if needed
        self._migrate_tables(cur)
        
        conn.commit()
        conn.close()
    
    def _migrate_tables(self, cur):
        """Add new columns to existing tables if they don't exist"""
        try:
            # Check if retries column exists
            cur.execute("PRAGMA table_info(analytics_services)")
            columns = [col[1] for col in cur.fetchall()]
            
            if 'retries' not in columns:
                logger.info("Migrating analytics_services table: adding retry columns")
                cur.execute("ALTER TABLE analytics_services ADD COLUMN retries INTEGER DEFAULT 3")
            
            if 'flap_window' not in columns:
                cur.execute("ALTER TABLE analytics_services ADD COLUMN flap_window INTEGER DEFAULT 3600")
            
            if 'flap_threshold' not in columns:
                cur.execute("ALTER TABLE analytics_services ADD COLUMN flap_threshold INTEGER DEFAULT 5")
            
            if 'suppression_duration' not in columns:
                cur.execute("ALTER TABLE analytics_services ADD COLUMN suppression_duration INTEGER DEFAULT 3600")
                
        except Exception as e:
            logger.error(f"Migration error: {e}")
    
    def add_service(self, service: HealthCheck):
        """Add a new service to monitor"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO analytics_services 
            (service_name, endpoint, check_type, expected_status, timeout, check_interval, enabled, 
             retries, flap_window, flap_threshold, suppression_duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            service.service_name, service.endpoint, service.check_type,
            service.expected_status, service.timeout, service.interval, 
            1 if service.enabled else 0, service.retries, service.flap_window,
            service.flap_threshold, service.suppression_duration
        ))
        
        conn.commit()
        conn.close()
    
    def update_service(self, service_id: int, data: Dict[str, Any]):
        """Update service configuration"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        fields = []
        values = []
        
        if 'service_name' in data:
            fields.append('service_name = ?')
            values.append(data['service_name'])
        if 'endpoint' in data:
            fields.append('endpoint = ?')
            values.append(data['endpoint'])
        if 'check_type' in data:
            fields.append('check_type = ?')
            values.append(data['check_type'])
        if 'expected_status' in data:
            fields.append('expected_status = ?')
            values.append(data['expected_status'])
        if 'timeout' in data:
            fields.append('timeout = ?')
            values.append(data['timeout'])
        if 'check_interval' in data:
            fields.append('check_interval = ?')
            values.append(data['check_interval'])
        if 'enabled' in data:
            fields.append('enabled = ?')
            values.append(1 if data['enabled'] else 0)
        if 'retries' in data:
            fields.append('retries = ?')
            values.append(data['retries'])
        if 'flap_window' in data:
            fields.append('flap_window = ?')
            values.append(data['flap_window'])
        if 'flap_threshold' in data:
            fields.append('flap_threshold = ?')
            values.append(data['flap_threshold'])
        if 'suppression_duration' in data:
            fields.append('suppression_duration = ?')
            values.append(data['suppression_duration'])
        
        if fields:
            values.append(service_id)
            query = f"UPDATE analytics_services SET {', '.join(fields)} WHERE id = ?"
            cur.execute(query, values)
        
        conn.commit()
        conn.close()
    
    def get_services(self) -> List[Dict]:
        """Get all services"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, service_name, endpoint, check_type, expected_status, timeout, 
                   check_interval, enabled, retries, flap_window, flap_threshold, 
                   suppression_duration, created_at
            FROM analytics_services
        """)
        
        services = []
        for row in cur.fetchall():
            services.append({
                'id': row[0],
                'service_name': row[1],
                'endpoint': row[2],
                'check_type': row[3],
                'expected_status': row[4],
                'timeout': row[5],
                'check_interval': row[6],
                'enabled': bool(row[7]),
                'retries': row[8],
                'flap_window': row[9],
                'flap_threshold': row[10],
                'suppression_duration': row[11],
                'created_at': row[12]
            })
        
        conn.close()
        return services
    
    def get_service(self, service_id: int) -> Optional[Dict]:
        """Get single service by ID"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, service_name, endpoint, check_type, expected_status, timeout, 
                   check_interval, enabled, retries, flap_window, flap_threshold, 
                   suppression_duration, created_at
            FROM analytics_services WHERE id = ?
        """, (service_id,))
        
        row = cur.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row[0],
                'service_name': row[1],
                'endpoint': row[2],
                'check_type': row[3],
                'expected_status': row[4],
                'timeout': row[5],
                'check_interval': row[6],
                'enabled': bool(row[7]),
                'retries': row[8],
                'flap_window': row[9],
                'flap_threshold': row[10],
                'suppression_duration': row[11],
                'created_at': row[12]
            }
        return None
    
    def delete_service(self, service_id: int):
        """Delete a service and its metrics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Get service name first
        cur.execute("SELECT service_name FROM analytics_services WHERE id = ?", (service_id,))
        row = cur.fetchone()
        
        if row:
            service_name = row[0]
            cur.execute("DELETE FROM analytics_metrics WHERE service_name = ?", (service_name,))
            cur.execute("DELETE FROM analytics_incidents WHERE service_name = ?", (service_name,))
            cur.execute("DELETE FROM analytics_services WHERE id = ?", (service_id,))
        
        conn.commit()
        conn.close()
    
    def record_metric(self, metric: ServiceMetric):
        """Record a health check metric"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO analytics_metrics 
            (service_name, timestamp, status, response_time, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (
            metric.service_name, metric.timestamp, metric.status,
            metric.response_time, metric.error_message
        ))
        
        conn.commit()
        conn.close()
    
    def record_incident(self, service_name: str, status: str, error_message: Optional[str] = None):
        """Record a new incident"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        timestamp = int(datetime.now().timestamp())
        
        cur.execute("""
            INSERT INTO analytics_incidents 
            (service_name, incident_start, status, error_message)
            VALUES (?, ?, ?, ?)
        """, (service_name, timestamp, status, error_message))
        
        conn.commit()
        conn.close()
    
    def close_incident(self, service_name: str):
        """Close the most recent open incident"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        timestamp = int(datetime.now().timestamp())
        
        cur.execute("""
            UPDATE analytics_incidents 
            SET incident_end = ? 
            WHERE service_name = ? AND incident_end IS NULL
            ORDER BY incident_start DESC
            LIMIT 1
        """, (timestamp, service_name))
        
        conn.commit()
        conn.close()
    
    def get_uptime_stats(self, service_name: str, hours: int = 24) -> Optional[Dict]:
        """Calculate uptime statistics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cutoff = int(datetime.now().timestamp()) - (hours * 3600)
        
        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM analytics_metrics
            WHERE service_name = ? AND timestamp >= ?
            GROUP BY status
        """, (service_name, cutoff))
        
        stats = {'up': 0, 'down': 0, 'degraded': 0}
        total = 0
        
        for row in cur.fetchall():
            stats[row[0]] = row[1]
            total += row[1]
        
        conn.close()
        
        if total == 0:
            return None
        
        uptime_pct = (stats['up'] / total) * 100
        
        return {
            'service_name': service_name,
            'hours': hours,
            'uptime_percentage': round(uptime_pct, 2),
            'total_checks': total,
            'up_count': stats['up'],
            'down_count': stats['down'],
            'degraded_count': stats['degraded']
        }
    
    def get_recent_incidents(self, days: int = 7) -> List[Dict]:
        """Get recent incidents"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cutoff = int(datetime.now().timestamp()) - (days * 86400)
        
        cur.execute("""
            SELECT service_name, incident_start, incident_end, status, error_message
            FROM analytics_incidents
            WHERE incident_start >= ?
            ORDER BY incident_start DESC
        """, (cutoff,))
        
        incidents = []
        for row in cur.fetchall():
            duration = None
            if row[2]:  # incident_end
                duration = row[2] - row[1]
            
            incidents.append({
                'service_name': row[0],
                'incident_start': row[1],
                'incident_end': row[2],
                'duration': duration,
                'status': row[3],
                'error_message': row[4]
            })
        
        conn.close()
        return incidents
    
    def get_health_score(self) -> Dict:
        """Calculate overall health score"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Get latest status for each service
        cur.execute("""
            SELECT DISTINCT service_name FROM analytics_services WHERE enabled = 1
        """)
        
        services = [row[0] for row in cur.fetchall()]
        total_services = len(services)
        
        if total_services == 0:
            conn.close()
            return {
                'health_score': 0,
                'total_services': 0,
                'services_up': 0,
                'services_down': 0,
                'services_degraded': 0
            }
        
        up_count = 0
        down_count = 0
        degraded_count = 0
        
        for service_name in services:
            cur.execute("""
                SELECT status FROM analytics_metrics
                WHERE service_name = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (service_name,))
            
            row = cur.fetchone()
            if row:
                status = row[0]
                if status == 'up':
                    up_count += 1
                elif status == 'down':
                    down_count += 1
                else:
                    degraded_count += 1
        
        conn.close()
        
        health_score = (up_count / total_services) * 100 if total_services > 0 else 0
        
        return {
            'health_score': round(health_score, 2),
            'total_services': total_services,
            'services_up': up_count,
            'services_down': down_count,
            'services_degraded': degraded_count
        }
    
    def purge_metrics_older_than(self, days: int) -> int:
        """Delete metrics older than specified days"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cutoff = int(datetime.now().timestamp()) - (days * 86400)
        
        cur.execute("DELETE FROM analytics_metrics WHERE timestamp < ?", (cutoff,))
        deleted = cur.rowcount
        
        conn.commit()
        conn.close()
        
        return deleted
    
    def reset_health_scores(self):
        """Reset all health metrics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM analytics_metrics")
        
        conn.commit()
        conn.close()
    
    def clear_incidents(self):
        """Clear all incident records"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM analytics_incidents")
        
        conn.commit()
        conn.close()


class HealthMonitor:
    """Service health monitoring with retries and flap protection"""
    
    def __init__(self, db: AnalyticsDB, notify_callback=None):
        self.db = db
        self.notify_callback = notify_callback
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.flap_trackers: Dict[str, FlapTracker] = {}
    
    async def check_http(self, endpoint: str, expected_status: int, timeout: int) -> tuple[bool, float, Optional[str]]:
        """Perform HTTP health check"""
        start_time = datetime.now()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                    response_time = (datetime.now() - start_time).total_seconds()
                    
                    if response.status == expected_status:
                        return True, response_time, None
                    else:
                        return False, response_time, f"HTTP {response.status} (expected {expected_status})"
        
        except asyncio.TimeoutError:
            response_time = (datetime.now() - start_time).total_seconds()
            return False, response_time, "Timeout"
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds()
            return False, response_time, str(e)
    
    async def check_tcp(self, endpoint: str, timeout: int) -> tuple[bool, float, Optional[str]]:
        """Perform TCP health check"""
        start_time = datetime.now()
        
        try:
            # Parse host:port
            if ':' in endpoint:
                host, port = endpoint.rsplit(':', 1)
                port = int(port)
            else:
                return False, 0, "Invalid TCP endpoint (use host:port)"
            
            # Remove protocol if present
            host = host.replace('http://', '').replace('https://', '')
            
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            
            writer.close()
            await writer.wait_closed()
            
            response_time = (datetime.now() - start_time).total_seconds()
            return True, response_time, None
        
        except asyncio.TimeoutError:
            response_time = (datetime.now() - start_time).total_seconds()
            return False, response_time, "Timeout"
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds()
            return False, response_time, str(e)
    
    async def check_ping(self, endpoint: str, timeout: int) -> tuple[bool, float, Optional[str]]:
        """Perform ICMP ping check"""
        start_time = datetime.now()
        
        try:
            # Remove protocol if present
            host = endpoint.replace('http://', '').replace('https://', '').split(':')[0]
            
            proc = await asyncio.create_subprocess_exec(
                'ping', '-c', '1', '-W', str(timeout), host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 1)
            response_time = (datetime.now() - start_time).total_seconds()
            
            if proc.returncode == 0:
                return True, response_time, None
            else:
                return False, response_time, "Ping failed"
        
        except asyncio.TimeoutError:
            response_time = (datetime.now() - start_time).total_seconds()
            return False, response_time, "Timeout"
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds()
            return False, response_time, str(e)
    
    def is_flapping(self, service_name: str, service: HealthCheck) -> bool:
        """Check if service is currently flapping"""
        tracker = self.flap_trackers.get(service_name)
        if not tracker:
            return False
        
        # Check if currently suppressed
        now = datetime.now().timestamp()
        if tracker.suppressed_until and now < tracker.suppressed_until:
            return True
        
        # Clean old flaps outside window
        cutoff = now - service.flap_window
        while tracker.flap_times and tracker.flap_times[0] < cutoff:
            tracker.flap_times.popleft()
        
        # Check if threshold exceeded
        if len(tracker.flap_times) >= service.flap_threshold:
            # Start suppression
            tracker.suppressed_until = now + service.suppression_duration
            logger.warning(
                f"Service {service_name} flapping detected: {len(tracker.flap_times)} flaps in {service.flap_window}s. "
                f"Suppressing alerts for {service.suppression_duration}s"
            )
            return True
        
        return False
    
    def record_status_change(self, service_name: str, new_status: str):
        """Record a status change for flap detection"""
        if service_name not in self.flap_trackers:
            self.flap_trackers[service_name] = FlapTracker()
        
        tracker = self.flap_trackers[service_name]
        
        # Only count as flap if status actually changed
        if tracker.last_status and tracker.last_status != new_status:
            tracker.flap_times.append(datetime.now().timestamp())
        
        tracker.last_status = new_status
    
    async def perform_check(self, service: HealthCheck) -> tuple[bool, float, Optional[str]]:
        """Perform health check with retries"""
        service_name = service.service_name
        tracker = self.flap_trackers.get(service_name)
        if not tracker:
            self.flap_trackers[service_name] = FlapTracker()
            tracker = self.flap_trackers[service_name]
        
        # Perform check based on type
        if service.check_type == 'http':
            success, response_time, error = await self.check_http(
                service.endpoint, service.expected_status, service.timeout
            )
        elif service.check_type == 'tcp':
            success, response_time, error = await self.check_tcp(
                service.endpoint, service.timeout
            )
        elif service.check_type == 'ping':
            success, response_time, error = await self.check_ping(
                service.endpoint, service.timeout
            )
        else:
            return False, 0, f"Unknown check type: {service.check_type}"
        
        # Handle retries for failures
        if not success:
            tracker.consecutive_failures += 1
            
            # Only mark as DOWN after exceeding retries
            if tracker.consecutive_failures >= service.retries:
                logger.warning(
                    f"Service {service_name} failed {tracker.consecutive_failures} consecutive checks "
                    f"(threshold: {service.retries})"
                )
                return False, response_time, error
            else:
                # Still in retry window, don't mark as DOWN yet
                logger.debug(
                    f"Service {service_name} check failed ({tracker.consecutive_failures}/{service.retries}), retrying..."
                )
                return True, response_time, None  # Treat as UP during retry window
        else:
            # Success - reset failure counter
            tracker.consecutive_failures = 0
        
        return success, response_time, error
    
    async def monitor_service(self, service: HealthCheck):
        """Monitor a single service continuously"""
        service_name = service.service_name
        logger.info(f"Starting health monitor for {service_name}")
        
        while True:
            try:
                # Perform health check with retries
                success, response_time, error = await self.perform_check(service)
                
                # Determine status
                status = 'up' if success else 'down'
                
                # Record metric
                metric = ServiceMetric(
                    service_name=service_name,
                    timestamp=int(datetime.now().timestamp()),
                    status=status,
                    response_time=response_time,
                    error_message=error
                )
                self.db.record_metric(metric)
                
                # Check for status change
                tracker = self.flap_trackers.get(service_name)
                if tracker and tracker.last_status != status:
                    self.record_status_change(service_name, status)
                    
                    # Check if flapping
                    is_flapping = self.is_flapping(service_name, service)
                    
                    # Send notification if not suppressed
                    if not is_flapping:
                        if status == 'down':
                            self.db.record_incident(service_name, status, error)
                            if self.notify_callback:
                                self.notify_callback({
                                    'service': service_name,
                                    'status': 'down',
                                    'message': error or 'Service check failed'
                                })
                        elif status == 'up' and tracker.last_status == 'down':
                            self.db.close_incident(service_name)
                            if self.notify_callback:
                                self.notify_callback({
                                    'service': service_name,
                                    'status': 'up',
                                    'message': 'Service recovered'
                                })
                    else:
                        logger.debug(f"Alert suppressed for {service_name} (flapping)")
                
                # Wait for next check
                await asyncio.sleep(service.interval)
            
            except asyncio.CancelledError:
                logger.info(f"Stopping health monitor for {service_name}")
                break
            except Exception as e:
                logger.error(f"Error monitoring {service_name}: {e}")
                await asyncio.sleep(service.interval)
    
    async def start_all_monitors(self):
        """Start monitoring all enabled services"""
        services = self.db.get_services()
        
        for service_data in services:
            if service_data['enabled']:
                service = HealthCheck(
                    service_name=service_data['service_name'],
                    endpoint=service_data['endpoint'],
                    check_type=service_data['check_type'],
                    expected_status=service_data['expected_status'],
                    timeout=service_data['timeout'],
                    interval=service_data['check_interval'],
                    enabled=service_data['enabled'],
                    retries=service_data.get('retries', 3),
                    flap_window=service_data.get('flap_window', 3600),
                    flap_threshold=service_data.get('flap_threshold', 5),
                    suppression_duration=service_data.get('suppression_duration', 3600)
                )
                
                task = asyncio.create_task(self.monitor_service(service))
                self.monitoring_tasks[service.service_name] = task
        
        logger.info(f"Started monitoring {len(self.monitoring_tasks)} services")


# Global instances
db: Optional[AnalyticsDB] = None
monitor: Optional[HealthMonitor] = None


def init_analytics(db_path: str = "/data/jarvis.db", notify_callback=None):
    """Initialize analytics module"""
    global db, monitor
    db = AnalyticsDB(db_path)
    
    # Default notify handler
    def analytics_notify(event):
        msg = f"[Analytics] {event['service']} is {event['status'].upper()} — {event['message']}"
        notify_error(msg, context="analytics")
    
    monitor = HealthMonitor(db, notify_callback=notify_callback or analytics_notify)
    
    # Auto-purge old metrics on startup
    try:
        deleted = db.purge_metrics_older_than(90)
        logger.info(f"Startup auto-purge: removed {deleted} metrics older than 90 days")
    except Exception as e:
        logger.error(f"Failed to auto-purge old metrics: {e}")
    
    # Auto-start monitoring
    async def safe_start():
        await asyncio.sleep(1)
        try:
            await monitor.start_all_monitors()
        except Exception as e:
            logger.error(f"Failed to auto-start monitors: {e}")
    
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(safe_start())
    except RuntimeError:
        logger.warning("Event loop not ready, monitors will need manual start")
    
    return db, monitor


# ============================================
# HTTP API Routes (aiohttp)
# ============================================

def _json(data, status=200):
    """Helper to create JSON response"""
    return web.json_response(data, status=status)


async def get_health_score(request: web.Request):
    """Get overall health score"""
    score = db.get_health_score()
    return _json(score)


async def get_services(request: web.Request):
    """Get all services with flap status"""
    services = db.get_services()
    
    # Add flap status to each service
    for service in services:
        service_name = service['service_name']
        tracker = monitor.flap_trackers.get(service_name) if monitor else None
        
        if tracker:
            now = datetime.now().timestamp()
            
            # Clean old flaps
            cutoff = now - service['flap_window']
            flap_times = [t for t in tracker.flap_times if t >= cutoff]
            
            service['flap_count'] = len(flap_times)
            service['is_suppressed'] = tracker.suppressed_until and now < tracker.suppressed_until
            service['suppressed_until'] = tracker.suppressed_until if service['is_suppressed'] else None
        else:
            service['flap_count'] = 0
            service['is_suppressed'] = False
            service['suppressed_until'] = None
    
    return _json(services)


async def get_service(request: web.Request):
    """Get single service by ID"""
    service_id = int(request.match_info["service_id"])
    service = db.get_service(service_id)
    
    if service:
        return _json(service)
    return _json({"error": "Service not found"}, status=404)


async def add_service(request: web.Request):
    """Add a new service"""
    data = await request.json()
    
    service = HealthCheck(
        service_name=data['service_name'],
        endpoint=data['endpoint'],
        check_type=data['check_type'],
        expected_status=data.get('expected_status', 200),
        timeout=data.get('timeout', 5),
        interval=data.get('check_interval', 60),
        enabled=data.get('enabled', True),
        retries=data.get('retries', 3),
        flap_window=data.get('flap_window', 3600),
        flap_threshold=data.get('flap_threshold', 5),
        suppression_duration=data.get('suppression_duration', 3600)
    )
    
    db.add_service(service)
    
    # Start monitoring if enabled
    if service.enabled and monitor:
        if service.service_name in monitor.monitoring_tasks:
            monitor.monitoring_tasks[service.service_name].cancel()
        
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({"success": True})


async def update_service(request: web.Request):
    """Update a service"""
    service_id = int(request.match_info["service_id"])
    data = await request.json()
    
    db.update_service(service_id, data)
    
    # Restart monitoring if enabled
    service_dict = db.get_service(service_id)
    if service_dict and monitor:
        service = HealthCheck(
            service_name=service_dict['service_name'],
            endpoint=service_dict['endpoint'],
            check_type=service_dict['check_type'],
            expected_status=service_dict['expected_status'],
            timeout=service_dict['timeout'],
            interval=service_dict['check_interval'],
            enabled=service_dict['enabled'],
            retries=service_dict.get('retries', 3),
            flap_window=service_dict.get('flap_window', 3600),
            flap_threshold=service_dict.get('flap_threshold', 5),
            suppression_duration=service_dict.get('suppression_duration', 3600)
        )
        
        if service.service_name in monitor.monitoring_tasks:
            monitor.monitoring_tasks[service.service_name].cancel()
        
        if service.enabled:
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
        if service_name in monitor.flap_trackers:
            del monitor.flap_trackers[service_name]
    
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


async def reset_health(request: web.Request):
    """Reset health scores"""
    db.reset_health_scores()
    return _json({"success": True})


async def reset_incidents(request: web.Request):
    """Clear all incidents"""
    db.clear_incidents()
    return _json({"success": True})


async def purge_metrics(request: web.Request):
    """Purge old metrics"""
    days = int(request.rel_url.query.get('days', 7))
    deleted = db.purge_metrics_older_than(days)
    return _json({"success": True, "deleted": deleted})


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
    app.router.add_post('/api/analytics/reset-health', reset_health)
    app.router.add_post('/api/analytics/reset-incidents', reset_incidents)
    app.router.add_post('/api/analytics/purge-metrics', purge_metrics)
