"""
Jarvis Prime - Analytics & Uptime Monitoring Module
aiohttp-compatible version for Jarvis Prime
PATCHED: Now includes dual notification support (process_incoming fan-out + legacy callback)
PATCHED: get_incidents now returns consistent { "incidents": [...] } format
PATCHED: analytics_notify is now always used as the primary callback
UPGRADED: Added retries and flap protection features
UPGRADED: Added NetAlertX-style network device scanning and monitoring
FIXED: Removed external dependencies (errors module)
"""

import sqlite3
import time
import json
import asyncio
import subprocess
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from aiohttp import web
from collections import deque
import logging
import re

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
    flap_times: deque = field(default_factory=deque)
    suppressed_until: Optional[float] = None
    last_status: Optional[str] = None
    consecutive_failures: int = 0


@dataclass
class NetworkDevice:
    """Network device discovered during scan"""
    mac_address: str
    ip_address: str
    hostname: Optional[str] = None
    vendor: Optional[str] = None
    custom_name: Optional[str] = None
    first_seen: Optional[int] = None
    last_seen: Optional[int] = None
    is_permanent: bool = False
    is_monitored: bool = False


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
                retries INTEGER DEFAULT 3,
                flap_window INTEGER DEFAULT 3600,
                flap_threshold INTEGER DEFAULT 5,
                suppression_duration INTEGER DEFAULT 3600,
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
        
        # Network devices table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS network_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac_address TEXT NOT NULL UNIQUE,
                ip_address TEXT,
                hostname TEXT,
                vendor TEXT,
                custom_name TEXT,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                is_permanent INTEGER DEFAULT 0,
                is_monitored INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        # Network scan history
        cur.execute("""
            CREATE TABLE IF NOT EXISTS network_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_timestamp INTEGER NOT NULL,
                devices_found INTEGER DEFAULT 0,
                scan_duration REAL,
                scan_type TEXT DEFAULT 'arp'
            )
        """)
        
        # Network events (new devices, disconnections, etc.)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS network_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                mac_address TEXT NOT NULL,
                ip_address TEXT,
                hostname TEXT,
                timestamp INTEGER NOT NULL,
                notified INTEGER DEFAULT 0
            )
        """)
        
        # Create indices
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_network_devices_mac 
            ON network_devices(mac_address)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_network_events_time 
            ON network_events(timestamp DESC)
        """)
        
        # Migrate existing tables
        self._migrate_tables(cur)
        
        conn.commit()
        conn.close()
        logger.info("Analytics database initialized with network monitoring")
    
    def _migrate_tables(self, cur):
        """Add new columns to existing tables if they don't exist"""
        try:
            cur.execute("PRAGMA table_info(analytics_services)")
            columns = [col[1] for col in cur.fetchall()]
            
            if 'retries' not in columns:
                logger.info("Migrating: adding retries column")
                cur.execute("ALTER TABLE analytics_services ADD COLUMN retries INTEGER DEFAULT 3")
            
            if 'flap_window' not in columns:
                logger.info("Migrating: adding flap_window column")
                cur.execute("ALTER TABLE analytics_services ADD COLUMN flap_window INTEGER DEFAULT 3600")
            
            if 'flap_threshold' not in columns:
                logger.info("Migrating: adding flap_threshold column")
                cur.execute("ALTER TABLE analytics_services ADD COLUMN flap_threshold INTEGER DEFAULT 5")
            
            if 'suppression_duration' not in columns:
                logger.info("Migrating: adding suppression_duration column")
                cur.execute("ALTER TABLE analytics_services ADD COLUMN suppression_duration INTEGER DEFAULT 3600")
            
            # Migrate network_devices table if it exists
            try:
                cur.execute("PRAGMA table_info(network_devices)")
                net_columns = [col[1] for col in cur.fetchall()]
                
                if net_columns and 'custom_name' not in net_columns:
                    logger.info("Migrating: adding custom_name column to network_devices")
                    cur.execute("ALTER TABLE network_devices ADD COLUMN custom_name TEXT")
            except Exception:
                pass  # Table doesn't exist yet
                
        except Exception as e:
            logger.error(f"Migration error: {e}")
    
    def add_service(self, service: HealthCheck) -> int:
        """Add or update a service configuration"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO analytics_services 
            (service_name, endpoint, check_type, expected_status, timeout, check_interval, enabled,
             retries, flap_window, flap_threshold, suppression_duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_name) DO UPDATE SET
                endpoint=excluded.endpoint,
                check_type=excluded.check_type,
                expected_status=excluded.expected_status,
                timeout=excluded.timeout,
                check_interval=excluded.check_interval,
                enabled=excluded.enabled,
                retries=excluded.retries,
                flap_window=excluded.flap_window,
                flap_threshold=excluded.flap_threshold,
                suppression_duration=excluded.suppression_duration,
                updated_at=strftime('%s', 'now')
        """, (service.service_name, service.endpoint, service.check_type,
              service.expected_status, service.timeout, service.interval,
              int(service.enabled), service.retries, service.flap_window,
              service.flap_threshold, service.suppression_duration))
        
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
                retries,
                flap_window,
                flap_threshold,
                suppression_duration,
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
        """Get a specific service by ID"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM analytics_services WHERE id = ?
        """, (service_id,))
        
        row = cur.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def delete_service(self, service_id: int):
        """Delete a service and its metrics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        service = self.get_service(service_id)
        if service:
            service_name = service['service_name']
            cur.execute("DELETE FROM analytics_metrics WHERE service_name = ?", (service_name,))
            cur.execute("DELETE FROM analytics_incidents WHERE service_name = ?", (service_name,))
            cur.execute("DELETE FROM analytics_services WHERE id = ?", (service_id,))
        
        conn.commit()
        conn.close()
    
    def record_metric(self, metric: ServiceMetric):
        """Record a service health check result"""
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
    
    def get_latest_metrics(self, hours: int = 24) -> List[Dict]:
        """Get latest metrics for all services"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (hours * 3600)
        
        cur.execute("""
            SELECT 
                service_name,
                status,
                response_time,
                timestamp,
                error_message
            FROM analytics_metrics
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """, (cutoff,))
        
        metrics = [dict(row) for row in cur.fetchall()]
        conn.close()
        return metrics
    
    def get_uptime_stats(self, service_name: str, hours: int = 24) -> Optional[Dict]:
        """Calculate uptime statistics for a service"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (hours * 3600)
        
        cur.execute("""
            SELECT 
                COUNT(*) as total_checks,
                SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END) as up_checks,
                SUM(CASE WHEN status = 'down' THEN 1 ELSE 0 END) as down_checks,
                SUM(CASE WHEN status = 'degraded' THEN 1 ELSE 0 END) as degraded_checks,
                AVG(response_time) as avg_response_time,
                MIN(response_time) as min_response_time,
                MAX(response_time) as max_response_time
            FROM analytics_metrics
            WHERE service_name = ? AND timestamp > ?
        """, (service_name, cutoff))
        
        row = cur.fetchone()
        conn.close()
        
        if row and row['total_checks'] > 0:
            stats = dict(row)
            stats['uptime_percentage'] = (stats['up_checks'] / stats['total_checks']) * 100
            # Round response times to 2 decimal places
            if stats.get('avg_response_time'):
                stats['avg_response_time'] = round(stats['avg_response_time'], 2)
            if stats.get('min_response_time'):
                stats['min_response_time'] = round(stats['min_response_time'], 2)
            if stats.get('max_response_time'):
                stats['max_response_time'] = round(stats['max_response_time'], 2)
            return stats
        
        return None
    
    def record_incident(self, service_name: str, start_time: int, error_message: str):
        """Record the start of a service incident"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO analytics_incidents 
            (service_name, start_time, error_message, status)
            VALUES (?, ?, ?, 'ongoing')
        """, (service_name, start_time, error_message))
        
        conn.commit()
        conn.close()
    
    def resolve_incident(self, service_name: str, end_time: int):
        """Resolve the most recent ongoing incident for a service"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE analytics_incidents
            SET end_time = ?,
                duration = ? - start_time,
                status = 'resolved'
            WHERE service_name = ?
                AND status = 'ongoing'
                AND id = (
                    SELECT id FROM analytics_incidents
                    WHERE service_name = ? AND status = 'ongoing'
                    ORDER BY start_time DESC
                    LIMIT 1
                )
        """, (end_time, end_time, service_name, service_name))
        
        conn.commit()
        conn.close()
    
    def get_recent_incidents(self, days: int = 7) -> List[Dict]:
        """Get recent incidents"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (days * 86400)
        
        cur.execute("""
            SELECT 
                id,
                service_name,
                start_time,
                end_time,
                duration,
                status,
                error_message
            FROM analytics_incidents
            WHERE start_time > ?
            ORDER BY start_time DESC
            LIMIT 100
        """, (cutoff,))
        
        incidents = [dict(row) for row in cur.fetchall()]
        conn.close()
        return incidents
    
    def purge_metrics_older_than(self, days: int) -> int:
        """Delete metrics older than specified days"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (days * 86400)
        
        cur.execute("DELETE FROM analytics_metrics WHERE timestamp < ?", (cutoff,))
        deleted = cur.rowcount
        
        conn.commit()
        conn.close()
        return deleted
    
    def purge_all_metrics(self) -> int:
        """Delete all metrics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM analytics_metrics")
        deleted = cur.rowcount
        
        conn.commit()
        conn.close()
        return deleted
    
    # Network monitoring database methods
    
    def upsert_device(self, device: NetworkDevice) -> int:
        """Add or update a network device"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        now = int(time.time())
        
        cur.execute("""
            INSERT INTO network_devices 
            (mac_address, ip_address, hostname, vendor, custom_name, first_seen, last_seen, 
             is_permanent, is_monitored)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac_address) DO UPDATE SET
                ip_address=excluded.ip_address,
                hostname=excluded.hostname,
                vendor=excluded.vendor,
                custom_name=COALESCE(excluded.custom_name, custom_name),
                last_seen=excluded.last_seen,
                is_permanent=excluded.is_permanent,
                is_monitored=excluded.is_monitored,
                updated_at=strftime('%s', 'now')
        """, (device.mac_address, device.ip_address, device.hostname, device.vendor,
              device.custom_name, device.first_seen or now, device.last_seen or now,
              int(device.is_permanent), int(device.is_monitored)))
        
        device_id = cur.lastrowid
        conn.commit()
        conn.close()
        return device_id
    
    def get_all_devices(self) -> List[Dict]:
        """Get all known network devices"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                id,
                mac_address,
                ip_address,
                hostname,
                vendor,
                custom_name,
                first_seen,
                last_seen,
                is_permanent,
                is_monitored
            FROM network_devices
            ORDER BY last_seen DESC
        """)
        
        devices = [dict(row) for row in cur.fetchall()]
        conn.close()
        return devices
    
    def get_device(self, mac_address: str) -> Optional[Dict]:
        """Get a single device by MAC address"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                id,
                mac_address,
                ip_address,
                hostname,
                vendor,
                custom_name,
                first_seen,
                last_seen,
                is_permanent,
                is_monitored
            FROM network_devices
            WHERE mac_address = ?
        """, (mac_address,))
        
        row = cur.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_monitored_devices(self) -> List[Dict]:
        """Get devices that are being monitored"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                id,
                mac_address,
                ip_address,
                hostname,
                vendor,
                custom_name,
                first_seen,
                last_seen,
                is_permanent,
                is_monitored
            FROM network_devices
            WHERE is_monitored = 1
            ORDER BY last_seen DESC
        """)
        
        devices = [dict(row) for row in cur.fetchall()]
        conn.close()
        return devices
    
    def update_device_settings(self, mac_address: str, is_permanent: bool = None, 
                              is_monitored: bool = None, custom_name: str = None):
        """Update device monitoring settings"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        updates = []
        params = []
        
        if is_permanent is not None:
            updates.append("is_permanent = ?")
            params.append(int(is_permanent))
        
        if is_monitored is not None:
            updates.append("is_monitored = ?")
            params.append(int(is_monitored))
        
        if custom_name is not None:
            updates.append("custom_name = ?")
            params.append(custom_name if custom_name.strip() else None)
        
        if updates:
            updates.append("updated_at = strftime('%s', 'now')")
            params.append(mac_address)
            
            query = f"UPDATE network_devices SET {', '.join(updates)} WHERE mac_address = ?"
            cur.execute(query, params)
        
        conn.commit()
        conn.close()
    
    def delete_device(self, mac_address: str):
        """Delete a device from the database"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM network_devices WHERE mac_address = ?", (mac_address,))
        cur.execute("DELETE FROM network_events WHERE mac_address = ?", (mac_address,))
        
        conn.commit()
        conn.close()
    
    def record_scan(self, devices_found: int, scan_duration: float, scan_type: str = 'arp'):
        """Record a network scan"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO network_scans 
            (scan_timestamp, devices_found, scan_duration, scan_type)
            VALUES (?, ?, ?, ?)
        """, (int(time.time()), devices_found, scan_duration, scan_type))
        
        conn.commit()
        conn.close()
    
    def record_network_event(self, event_type: str, mac_address: str, 
                            ip_address: str = None, hostname: str = None):
        """Record a network event (new device, disconnection, etc.)"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO network_events 
            (event_type, mac_address, ip_address, hostname, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (event_type, mac_address, ip_address, hostname, int(time.time())))
        
        conn.commit()
        conn.close()
    
    def get_recent_network_events(self, hours: int = 24) -> List[Dict]:
        """Get recent network events"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (hours * 3600)
        
        cur.execute("""
            SELECT 
                id,
                event_type,
                mac_address,
                ip_address,
                hostname,
                timestamp,
                notified
            FROM network_events
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """, (cutoff,))
        
        events = [dict(row) for row in cur.fetchall()]
        conn.close()
        return events
    
    def get_network_stats(self) -> Dict:
        """Get network monitoring statistics"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Total devices
        cur.execute("SELECT COUNT(*) as total FROM network_devices")
        total = cur.fetchone()['total']
        
        # Monitored devices
        cur.execute("SELECT COUNT(*) as monitored FROM network_devices WHERE is_monitored = 1")
        monitored = cur.fetchone()['monitored']
        
        # Permanent devices
        cur.execute("SELECT COUNT(*) as permanent FROM network_devices WHERE is_permanent = 1")
        permanent = cur.fetchone()['permanent']
        
        # Recent scans
        cur.execute("""
            SELECT COUNT(*) as scan_count 
            FROM network_scans 
            WHERE scan_timestamp > ?
        """, (int(time.time()) - 86400,))
        scans_24h = cur.fetchone()['scan_count']
        
        # Recent events
        cur.execute("""
            SELECT COUNT(*) as event_count 
            FROM network_events 
            WHERE timestamp > ?
        """, (int(time.time()) - 86400,))
        events_24h = cur.fetchone()['event_count']
        
        # Last scan time
        cur.execute("""
            SELECT MAX(scan_timestamp) as last_scan 
            FROM network_scans
        """)
        last_scan = cur.fetchone()['last_scan']
        
        conn.close()
        
        return {
            'total_devices': total,
            'monitored_devices': monitored,
            'permanent_devices': permanent,
            'scans_24h': scans_24h,
            'events_24h': events_24h,
            'last_scan': last_scan
        }
    
    def check_ip_in_services(self, ip_address: str) -> bool:
        """Check if IP address already exists in analytics services"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Check if endpoint contains this IP
        cur.execute("""
            SELECT COUNT(*) as count
            FROM analytics_services
            WHERE endpoint LIKE ?
        """, (f'%{ip_address}%',))
        
        result = cur.fetchone()
        conn.close()
        
        return result[0] > 0


class NetworkScanner:
    """Network device scanner using ARP"""
    
    def __init__(self, db: AnalyticsDB):
        self.db = db
        self.scanning = False
        self.monitoring = False
        self.monitor_interval = 900  # 5 minutes
        self.monitor_task = None
        self.alert_new_devices = True
        self.notification_callback = None
    
    def set_notification_callback(self, callback: Callable):
        """Set callback for network notifications"""
        self.notification_callback = callback
    
    async def scan_network(self, interface: str = None, subnet: str = None) -> List[Dict]:
        """
        Perform ARP scan of local network
        Returns list of discovered devices
        """
        if self.scanning:
            logger.warning("Scan already in progress")
            return []
        
        self.scanning = True
        start_time = time.time()
        devices = []
        
        try:
            # Build arp-scan command
            cmd = ['arp-scan', '--localnet', '--retry=3', '--timeout=1000']
            
            if interface:
                cmd.extend(['--interface', interface])
            
            if subnet:
                cmd = ['arp-scan', subnet, '--retry=3', '--timeout=1000']
                if interface:
                    cmd.extend(['--interface', interface])
            
            logger.info(f"Running network scan: {' '.join(cmd)}")
            
            # Run arp-scan
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
                
                if process.returncode != 0:
                    error_msg = stderr.decode().strip()
                    logger.error(f"arp-scan failed (returncode {process.returncode}): {error_msg}")
                    # Fallback to ip neigh if arp-scan not available
                    return await self._fallback_scan()
                
                # Parse arp-scan output
                output = stdout.decode()
                for line in output.split('\n'):
                    # Match lines like: 192.168.1.1  00:11:22:33:44:55  Vendor Name
                    match = re.match(r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:]{17})\s*(.*)', line)
                    if match:
                        ip, mac, vendor = match.groups()
                        
                        # Try to resolve hostname
                        hostname = await self._resolve_hostname(ip)
                        
                        device_dict = {
                            'ip_address': ip,
                            'mac_address': mac.upper(),
                            'hostname': hostname,
                            'vendor': vendor.strip() if vendor else None
                        }
                        devices.append(device_dict)
                
                scan_duration = time.time() - start_time
                logger.info(f"Network scan complete: {len(devices)} devices found in {scan_duration:.2f}s")
                
                # Update database
                await self._process_scan_results(devices)
                self.db.record_scan(len(devices), scan_duration)
                
            except FileNotFoundError:
                logger.error("arp-scan not found, using fallback method (ip neigh)")
                devices = await self._fallback_scan()
            except asyncio.TimeoutError:
                logger.error("Network scan timed out after 30 seconds")
            except Exception as scan_error:
                logger.error(f"arp-scan execution error: {scan_error}")
                devices = await self._fallback_scan()
            
        except Exception as e:
            logger.error(f"Network scan error: {e}", exc_info=True)
        finally:
            self.scanning = False
        
        return devices
    
    async def _fallback_scan(self) -> List[Dict]:
        """Fallback scan using ip neigh (ARP cache)"""
        logger.info("Using fallback scan method (ip neigh)")
        devices = []
        start_time = time.time()
        
        try:
            process = await asyncio.create_subprocess_exec(
                'ip', 'neigh', 'show',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            output = stdout.decode()
            
            for line in output.split('\n'):
                # Match lines like: 192.168.1.1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE
                match = re.search(r'(\d+\.\d+\.\d+\.\d+).*lladdr\s+([0-9a-fA-F:]{17})', line)
                if match:
                    ip, mac = match.groups()
                    hostname = await self._resolve_hostname(ip)
                    
                    devices.append({
                        'ip_address': ip,
                        'mac_address': mac.upper(),
                        'hostname': hostname,
                        'vendor': None
                    })
            
            # Update database with fallback results
            if devices:
                await self._process_scan_results(devices)
                scan_duration = time.time() - start_time
                self.db.record_scan(len(devices), scan_duration)
                logger.info(f"Fallback scan found {len(devices)} devices in {scan_duration:.2f}s")
        
        except asyncio.TimeoutError:
            logger.error("Fallback scan timed out")
        except Exception as e:
            logger.error(f"Fallback scan error: {e}", exc_info=True)
        
        return devices
    
    async def _resolve_hostname(self, ip: str) -> Optional[str]:
        """Try to resolve hostname from IP"""
        try:
            process = await asyncio.create_subprocess_exec(
                'host', ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2.0)
            output = stdout.decode()
            
            # Parse output like: 1.168.192.in-addr.arpa domain name pointer hostname.local.
            match = re.search(r'pointer\s+(\S+)', output)
            if match:
                hostname = match.group(1).rstrip('.')
                return hostname
        
        except Exception:
            pass
        
        return None
    
    async def _process_scan_results(self, devices: List[Dict]):
        """Process scan results and update database"""
        now = int(time.time())
        known_macs = {d['mac_address'] for d in self.db.get_all_devices()}
        scanned_macs = {d['mac_address'] for d in devices}
        
        # Update existing devices and add new ones
        for device_dict in devices:
            mac = device_dict['mac_address']
            is_new = mac not in known_macs
            
            device = NetworkDevice(
                mac_address=mac,
                ip_address=device_dict['ip_address'],
                hostname=device_dict.get('hostname'),
                vendor=device_dict.get('vendor'),
                first_seen=now if is_new else None,
                last_seen=now
            )
            
            self.db.upsert_device(device)
            
            # Record event for new devices
            if is_new:
                logger.info(f"New device detected: {mac} ({device_dict['ip_address']})")
                self.db.record_network_event(
                    'new_device',
                    mac,
                    device_dict['ip_address'],
                    device_dict.get('hostname')
                )
                
                # Send notification if alerts enabled
                if self.alert_new_devices and self.notification_callback:
                    await self._notify_new_device(device_dict)
        
        # Detect offline monitored devices
        monitored_devices = self.db.get_monitored_devices()
        for device in monitored_devices:
            if device['mac_address'] not in scanned_macs:
                time_offline = now - device['last_seen']
                # Only alert if offline for > 10 minutes
                if time_offline > 600:
                    logger.warning(f"Monitored device offline: {device['mac_address']}")
                    self.db.record_network_event(
                        'device_offline',
                        device['mac_address'],
                        device['ip_address'],
                        device.get('hostname')
                    )
                    
                    if self.notification_callback:
                        await self._notify_device_offline(device)
    
    async def _notify_new_device(self, device: Dict):
        """Send notification for new device"""
        if not self.notification_callback:
            return
        
        message = (
            f"🔍 New device detected on network\n"
            f"MAC: {device['mac_address']}\n"
            f"IP: {device['ip_address']}\n"
        )
        
        if device.get('hostname'):
            message += f"Hostname: {device['hostname']}\n"
        if device.get('vendor'):
            message += f"Vendor: {device['vendor']}\n"
        
        try:
            await self.notification_callback("network", "info", message)
        except Exception as e:
            logger.error(f"Failed to send new device notification: {e}")
    
    async def _notify_device_offline(self, device: Dict):
        """Send notification for offline monitored device"""
        if not self.notification_callback:
            return
        
        message = (
            f"⚠️ Monitored device offline\n"
            f"MAC: {device['mac_address']}\n"
            f"IP: {device['ip_address']}\n"
        )
        
        if device.get('hostname'):
            message += f"Hostname: {device['hostname']}\n"
        
        try:
            await self.notification_callback("network", "warning", message)
        except Exception as e:
            logger.error(f"Failed to send offline device notification: {e}")
    
    async def start_monitoring(self):
        """Start continuous network monitoring"""
        if self.monitoring:
            logger.warning("Network monitoring already active")
            return
        
        self.monitoring = True
        self.monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Network monitoring started")
    
    async def stop_monitoring(self):
        """Stop continuous network monitoring"""
        self.monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Network monitoring stopped")
    
    async def _monitoring_loop(self):
        """Continuous monitoring loop"""
        while self.monitoring:
            try:
                await self.scan_network()
                await asyncio.sleep(self.monitor_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(60)
    
    def set_alert_new_devices(self, enabled: bool):
        """Enable/disable new device alerts"""
        self.alert_new_devices = enabled
        logger.info(f"New device alerts: {'enabled' if enabled else 'disabled'}")


class HealthMonitor:
    """Monitor service health with retry and flap protection"""
    
    def __init__(self, db: AnalyticsDB, notification_callback: Optional[Callable] = None):
        self.db = db
        self.notification_callback = notification_callback
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.flap_trackers: Dict[str, FlapTracker] = {}
    
    def set_notification_callback(self, callback: Callable):
        """Set or update the notification callback"""
        self.notification_callback = callback
        logger.info("Health monitor notification callback updated")
    
    async def check_http(self, endpoint: str, expected_status: int, timeout: int) -> tuple[str, float, Optional[str]]:
        """Perform HTTP health check"""
        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    response_time = time.time() - start
                    if resp.status == expected_status:
                        return 'up', response_time, None
                    else:
                        return 'degraded', response_time, f"HTTP {resp.status}"
        except asyncio.TimeoutError:
            return 'down', time.time() - start, 'Timeout'
        except Exception as e:
            return 'down', time.time() - start, str(e)
    
    async def check_tcp(self, endpoint: str, timeout: int) -> tuple[str, float, Optional[str]]:
        """Perform TCP port check"""
        start = time.time()
        try:
            # Parse endpoint (format: host:port)
            if ':' not in endpoint:
                return 'down', 0, 'Invalid endpoint format'
            
            host, port = endpoint.rsplit(':', 1)
            port = int(port)
            
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            
            return 'up', time.time() - start, None
        except asyncio.TimeoutError:
            return 'down', time.time() - start, 'Timeout'
        except Exception as e:
            return 'down', time.time() - start, str(e)
    
    async def check_ping(self, endpoint: str, timeout: int) -> tuple[str, float, Optional[str]]:
        """Perform ping check"""
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                'ping', '-c', '1', '-W', str(timeout), endpoint,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await proc.communicate()
            response_time = time.time() - start
            
            if proc.returncode == 0:
                return 'up', response_time, None
            else:
                return 'down', response_time, 'Ping failed'
        except Exception as e:
            return 'down', time.time() - start, str(e)
    
    async def perform_check(self, service: HealthCheck) -> ServiceMetric:
        """Perform a single health check with retries"""
        best_result = None
        
        for attempt in range(service.retries):
            if service.check_type == 'http':
                status, response_time, error = await self.check_http(
                    service.endpoint, service.expected_status, service.timeout
                )
            elif service.check_type == 'tcp':
                status, response_time, error = await self.check_tcp(
                    service.endpoint, service.timeout
                )
            elif service.check_type == 'ping':
                status, response_time, error = await self.check_ping(
                    service.endpoint, service.timeout
                )
            else:
                status, response_time, error = 'down', 0, f"Unknown check type: {service.check_type}"
            
            # If check succeeded, return immediately
            if status == 'up':
                return ServiceMetric(
                    service_name=service.service_name,
                    timestamp=int(time.time()),
                    status=status,
                    response_time=response_time,
                    error_message=error
                )
            
            # Store this attempt
            best_result = ServiceMetric(
                service_name=service.service_name,
                timestamp=int(time.time()),
                status=status,
                response_time=response_time,
                error_message=error
            )
            
            # Wait before retry (except on last attempt)
            if attempt < service.retries - 1:
                await asyncio.sleep(1)
        
        # All retries failed, return last result
        return best_result
    
    def is_flapping(self, service_name: str, new_status: str, config: HealthCheck) -> bool:
        """Check if service is flapping"""
        if service_name not in self.flap_trackers:
            self.flap_trackers[service_name] = FlapTracker()
        
        tracker = self.flap_trackers[service_name]
        now = time.time()
        
        # Check if currently suppressed
        if tracker.suppressed_until and now < tracker.suppressed_until:
            return True
        elif tracker.suppressed_until and now >= tracker.suppressed_until:
            # Suppression period ended
            tracker.suppressed_until = None
            tracker.flap_times.clear()
            logger.info(f"Flap suppression ended for {service_name}")
        
        # Detect state change
        if tracker.last_status and tracker.last_status != new_status:
            # Record flap time
            tracker.flap_times.append(now)
            
            # Remove old flap times outside window
            cutoff = now - config.flap_window
            while tracker.flap_times and tracker.flap_times[0] < cutoff:
                tracker.flap_times.popleft()
            
            # Check if threshold exceeded
            if len(tracker.flap_times) >= config.flap_threshold:
                logger.warning(
                    f"Service {service_name} is flapping "
                    f"({len(tracker.flap_times)} state changes in {config.flap_window}s). "
                    f"Suppressing notifications for {config.suppression_duration}s"
                )
                tracker.suppressed_until = now + config.suppression_duration
                return True
        
        tracker.last_status = new_status
        return False
    
    async def monitor_service(self, service: HealthCheck):
        """Monitor a service continuously"""
        logger.info(f"Starting monitoring for {service.service_name}")
        
        while True:
            try:
                metric = await self.perform_check(service)
                self.db.record_metric(metric)
                
                # Check for flapping
                is_flapping = self.is_flapping(service.service_name, metric.status, service)
                
                # Handle incidents (only if not flapping)
                if metric.status == 'down' and not is_flapping:
                    # Check if there's an ongoing incident
                    recent_incidents = self.db.get_recent_incidents(days=1)
                    has_ongoing = any(
                        inc['service_name'] == service.service_name and inc['status'] == 'ongoing'
                        for inc in recent_incidents
                    )
                    
                    if not has_ongoing:
                        self.db.record_incident(
                            service.service_name,
                            metric.timestamp,
                            metric.error_message or 'Service down'
                        )
                        
                        # Send notification
                        if self.notification_callback:
                            await self.notification_callback(
                                service.service_name,
                                'error',
                                f"Service {service.service_name} is DOWN: {metric.error_message}"
                            )
                
                elif metric.status == 'up':
                    # Resolve any ongoing incidents
                    recent_incidents = self.db.get_recent_incidents(days=1)
                    has_ongoing = any(
                        inc['service_name'] == service.service_name and inc['status'] == 'ongoing'
                        for inc in recent_incidents
                    )
                    
                    if has_ongoing:
                        self.db.resolve_incident(service.service_name, metric.timestamp)
                        
                        # Send recovery notification (only if not flapping)
                        if self.notification_callback and not is_flapping:
                            await self.notification_callback(
                                service.service_name,
                                'success',
                                f"Service {service.service_name} has recovered"
                            )
                
                await asyncio.sleep(service.interval)
                
            except asyncio.CancelledError:
                logger.info(f"Monitoring stopped for {service.service_name}")
                break
            except Exception as e:
                logger.error(f"Error monitoring {service.service_name}: {e}")
                await asyncio.sleep(60)
    
    async def start_all(self):
        """Start monitoring all enabled services"""
        services = self.db.get_all_services()
        for service_dict in services:
            if service_dict['enabled']:
                service = HealthCheck(
                    service_name=service_dict['service_name'],
                    endpoint=service_dict['endpoint'],
                    check_type=service_dict['check_type'],
                    expected_status=service_dict.get('expected_status', 200),
                    timeout=service_dict.get('timeout', 5),
                    interval=service_dict.get('check_interval', 60),
                    enabled=True,
                    retries=service_dict.get('retries', 3),
                    flap_window=service_dict.get('flap_window', 3600),
                    flap_threshold=service_dict.get('flap_threshold', 5),
                    suppression_duration=service_dict.get('suppression_duration', 3600)
                )
                
                task = asyncio.create_task(self.monitor_service(service))
                self.monitoring_tasks[service.service_name] = task
        
        logger.info(f"Started monitoring {len(self.monitoring_tasks)} services")
    
    async def stop_all(self):
        """Stop monitoring all services"""
        for task in self.monitoring_tasks.values():
            task.cancel()
        
        await asyncio.gather(*self.monitoring_tasks.values(), return_exceptions=True)
        self.monitoring_tasks.clear()
        logger.info("Stopped all service monitoring")


# Global instances
db = None
monitor = None
scanner = None


def _json(data, status=200):
    """Helper to create JSON response"""
    return web.json_response(data, status=status)


async def get_health_score(request: web.Request):
    """Calculate overall system health score"""
    services = db.get_all_services()
    
    if not services:
        return _json({
            'health_score': 100,
            'status': 'healthy',
            'message': 'No services configured',
            'total_services': 0,
            'up_services': 0,
            'down_services': 0,
            'enabled_services': 0
        })
    
    total_score = 0
    up_services = 0
    down_services = 0
    enabled_count = 0
    
    for service in services:
        if not service['enabled']:
            continue
        
        enabled_count += 1
        
        # Count up/down services
        if service.get('current_status') == 'up':
            up_services += 1
        else:
            down_services += 1
        
        stats = db.get_uptime_stats(service['service_name'], hours=24)
        if stats:
            total_score += stats['uptime_percentage']
        else:
            total_score += 100
    
    avg_score = total_score / enabled_count if enabled_count > 0 else 100
    
    if avg_score >= 95:
        status = 'healthy'
    elif avg_score >= 80:
        status = 'degraded'
    else:
        status = 'critical'
    
    return _json({
        'health_score': round(avg_score, 2),
        'status': status,
        'total_services': len(services),
        'up_services': up_services,
        'down_services': down_services,
        'enabled_services': enabled_count
    })


async def get_services(request: web.Request):
    """Get all services with flap detection info"""
    services = db.get_all_services()
    
    # Add flap tracking info if monitor exists
    if monitor:
        for service in services:
            service_name = service['service_name']
            if service_name in monitor.flap_trackers:
                tracker = monitor.flap_trackers[service_name]
                service['flap_count'] = len(tracker.flap_times)
                service['is_suppressed'] = (
                    tracker.suppressed_until is not None and 
                    time.time() < tracker.suppressed_until
                )
                service['suppressed_until'] = tracker.suppressed_until
        else:
            service['flap_count'] = 0
            service['is_suppressed'] = False
            service['suppressed_until'] = None
    
    return _json(services)


async def add_service(request: web.Request):
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
        enabled=data.get('enabled', True),
        retries=data.get('retries', 3),
        flap_window=data.get('flap_window', 3600),
        flap_threshold=data.get('flap_threshold', 5),
        suppression_duration=data.get('suppression_duration', 3600)
    )
    
    service_id = db.add_service(service)
    
    if service.enabled and monitor:
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({"success": True, "service_id": int(service_id)})


async def get_service(request: web.Request):
    service_id = int(request.match_info["service_id"])
    service = db.get_service(service_id)
    if service:
        return _json(service)
    return _json({"error": "Service not found"}, status=404)


async def update_service(request: web.Request):
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
        enabled=data.get('enabled', True),
        retries=data.get('retries', 3),
        flap_window=data.get('flap_window', 3600),
        flap_threshold=data.get('flap_threshold', 5),
        suppression_duration=data.get('suppression_duration', 3600)
    )
    
    db.add_service(service)
    
    if service.enabled and monitor:
        if service.service_name in monitor.monitoring_tasks:
            monitor.monitoring_tasks[service.service_name].cancel()
        
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({"success": True})


async def delete_service_route(request: web.Request):
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
    service_name = request.match_info["service_name"]
    hours = int(request.rel_url.query.get('hours', 24))
    
    stats = db.get_uptime_stats(service_name, hours)
    if stats:
        return _json(stats)
    return _json({"error": "No data found"}, status=404)


async def get_incidents(request: web.Request):
    """Get recent incidents for analytics dashboard"""
    try:
        days = int(request.rel_url.query.get('days', 7))
    except Exception:
        days = 7
    
    try:
        incidents = db.get_recent_incidents(days)
        return _json({"incidents": incidents})
    except Exception as e:
        logger.error(f"Failed to fetch incidents: {e}")
        return _json({"incidents": [], "error": str(e)}, status=500)


async def reset_health_score(request: web.Request):
    try:
        conn = sqlite3.connect(db.db_path)
        cur = conn.cursor()
        cur.execute('DELETE FROM analytics_metrics')
        conn.commit()
        conn.close()
        return _json({'success': True, 'message': 'Health scores reset'})
    except Exception as e:
        return _json({'success': False, 'error': str(e)}, status=500)


async def reset_incidents(request: web.Request):
    try:
        conn = sqlite3.connect(db.db_path)
        cur = conn.cursor()
        cur.execute('DELETE FROM analytics_incidents')
        conn.commit()
        conn.close()
        return _json({'success': True, 'message': 'All incidents cleared'})
    except Exception as e:
        return _json({'success': False, 'error': str(e)}, status=500)


async def reset_service_data(request: web.Request):
    service_name = request.match_info["service_name"]
    try:
        conn = sqlite3.connect(db.db_path)
        cur = conn.cursor()
        cur.execute('DELETE FROM analytics_metrics WHERE service_name = ?', (service_name,))
        cur.execute('DELETE FROM analytics_incidents WHERE service_name = ?', (service_name,))
        conn.commit()
        conn.close()
        return _json({'success': True, 'message': f'Data reset for {service_name}'})
    except Exception as e:
        return _json({'success': False, 'error': str(e)}, status=500)


async def purge_all_metrics(request: web.Request):
    try:
        deleted = db.purge_all_metrics()
        return _json({
            'success': True, 
            'deleted': deleted,
            'message': f'Purged all {deleted} metrics'
        })
    except Exception as e:
        logger.error(f"Purge all failed: {e}")
        return _json({'success': False, 'error': str(e)}, status=500)


async def purge_week_metrics(request: web.Request):
    try:
        deleted = db.purge_metrics_older_than(7)
        return _json({
            'success': True,
            'deleted': deleted,
            'days': 7,
            'message': f'Purged {deleted} metrics older than 1 week'
        })
    except Exception as e:
        logger.error(f"Purge week failed: {e}")
        return _json({'success': False, 'error': str(e)}, status=500)


async def purge_month_metrics(request: web.Request):
    try:
        deleted = db.purge_metrics_older_than(30)
        return _json({
            'success': True,
            'deleted': deleted,
            'days': 30,
            'message': f'Purged {deleted} metrics older than 1 month'
        })
    except Exception as e:
        logger.error(f"Purge month failed: {e}")
        return _json({'success': False, 'error': str(e)}, status=500)


# Network monitoring endpoints

async def network_scan(request: web.Request):
    """Trigger a network scan"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    
    interface = data.get('interface')
    subnet = data.get('subnet')
    
    devices = await scanner.scan_network(interface, subnet)
    
    return _json({
        'success': True,
        'devices_found': len(devices),
        'devices': devices
    })


async def get_network_devices(request: web.Request):
    """Get all known network devices with duplicate detection"""
    all_devices = db.get_all_devices()
    
    # Filter out devices that are already in services
    devices = []
    for device in all_devices:
        if device['ip_address']:
            in_services = db.check_ip_in_services(device['ip_address'])
            # Skip devices that are already in analytics services
            if not in_services:
                device['in_services'] = False
                devices.append(device)
        else:
            device['in_services'] = False
            devices.append(device)
    
    return _json({'devices': devices})


async def get_monitored_devices(request: web.Request):
    """Get devices being monitored"""
    devices = db.get_monitored_devices()
    return _json({'devices': devices})


async def update_device(request: web.Request):
    """Update device monitoring settings"""
    mac_address = request.match_info["mac_address"]
    
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    is_permanent = data.get('is_permanent')
    is_monitored = data.get('is_monitored')
    custom_name = data.get('custom_name')
    
    # Get device info before updating
    device = db.get_device(mac_address)
    
    if not device:
        return _json({"error": "Device not found"}, status=404)
    
    # If marking as permanent, auto-promote to Analytics Services
    if is_permanent and not device.get('is_permanent'):
        ip_address = device.get('ip_address')
        hostname = device.get('hostname') or device.get('custom_name')
        
        if ip_address:
            # Create service name
            service_name = custom_name or hostname or f"Device-{ip_address}"
            
            # Check if service already exists
            if not db.check_ip_in_services(ip_address):
                # Create health check service
                service = HealthCheck(
                    service_name=service_name,
                    endpoint=ip_address,
                    check_type='ping',
                    expected_status=200,
                    timeout=5,
                    interval=300,  # 5 minutes
                    enabled=True,
                    retries=3,
                    flap_window=3600,
                    flap_threshold=5,
                    suppression_duration=3600
                )
                
                try:
                    db.add_service(service)
                    
                    # Start monitoring if monitor exists
                    if monitor:
                        task = asyncio.create_task(monitor.monitor_service(service))
                        monitor.monitoring_tasks[service.service_name] = task
                    
                    logger.info(f"Auto-promoted device {mac_address} ({ip_address}) to Analytics Services as '{service_name}'")
                    
                    # Delete from network devices since it's now in services
                    db.delete_device(mac_address)
                    
                    return _json({
                        'success': True,
                        'promoted': True,
                        'service_name': service_name,
                        'message': f'Device promoted to Analytics Services as "{service_name}"'
                    })
                    
                except Exception as e:
                    logger.error(f"Failed to promote device to service: {e}")
                    # Fall through to regular update if promotion fails
    
    # Regular update if not promoting
    db.update_device_settings(mac_address, is_permanent, is_monitored, custom_name)
    
    return _json({'success': True})


async def delete_device(request: web.Request):
    """Delete a device"""
    mac_address = request.match_info["mac_address"]
    db.delete_device(mac_address)
    return _json({'success': True})


async def start_network_monitoring(request: web.Request):
    """Start continuous network monitoring"""
    await scanner.start_monitoring()
    return _json({'success': True, 'monitoring': True})


async def stop_network_monitoring(request: web.Request):
    """Stop continuous network monitoring"""
    await scanner.stop_monitoring()
    return _json({'success': True, 'monitoring': False})


async def get_network_monitoring_status(request: web.Request):
    """Get network monitoring status"""
    return _json({
        'monitoring': scanner.monitoring,
        'scanning': scanner.scanning,
        'alert_new_devices': scanner.alert_new_devices,
        'monitor_interval': scanner.monitor_interval
    })


async def update_network_settings(request: web.Request):
    """Update network monitoring settings"""
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    if 'alert_new_devices' in data:
        scanner.set_alert_new_devices(data['alert_new_devices'])
    
    if 'monitor_interval' in data:
        interval = int(data['monitor_interval'])
        if 60 <= interval <= 3600:
            scanner.monitor_interval = interval
    
    return _json({'success': True})


async def get_network_events(request: web.Request):
    """Get recent network events"""
    try:
        hours = int(request.rel_url.query.get('hours', 24))
    except Exception:
        hours = 24
    
    events = db.get_recent_network_events(hours)
    return _json({'events': events})


async def get_network_stats(request: web.Request):
    """Get network statistics"""
    stats = db.get_network_stats()
    return _json(stats)


def register_routes(app: web.Application):
    """Register analytics routes with aiohttp app"""
    # Service monitoring routes
    app.router.add_get('/api/analytics/health-score', get_health_score)
    app.router.add_get('/api/analytics/services', get_services)
    app.router.add_post('/api/analytics/services', add_service)
    app.router.add_get('/api/analytics/services/{service_id}', get_service)
    app.router.add_put('/api/analytics/services/{service_id}', update_service)
    app.router.add_delete('/api/analytics/services/{service_id}', delete_service_route)
    app.router.add_get('/api/analytics/uptime/{service_name}', get_uptime)
    app.router.add_get('/api/analytics/incidents', get_incidents)
    app.router.add_post('/api/analytics/reset-health', reset_health_score)
    app.router.add_post('/api/analytics/reset-incidents', reset_incidents)
    app.router.add_post('/api/analytics/reset-service/{service_name}', reset_service_data)
    app.router.add_post('/api/analytics/purge-all', purge_all_metrics)
    app.router.add_post('/api/analytics/purge-week', purge_week_metrics)
    app.router.add_post('/api/analytics/purge-month', purge_month_metrics)
    
    # Network monitoring routes
    app.router.add_post('/api/analytics/network/scan', network_scan)
    app.router.add_get('/api/analytics/network/devices', get_network_devices)
    app.router.add_get('/api/analytics/network/monitored', get_monitored_devices)
    app.router.add_put('/api/analytics/network/devices/{mac_address}', update_device)
    app.router.add_delete('/api/analytics/network/devices/{mac_address}', delete_device)
    app.router.add_post('/api/analytics/network/monitoring/start', start_network_monitoring)
    app.router.add_post('/api/analytics/network/monitoring/stop', stop_network_monitoring)
    app.router.add_get('/api/analytics/network/monitoring/status', get_network_monitoring_status)
    app.router.add_put('/api/analytics/network/settings', update_network_settings)
    app.router.add_get('/api/analytics/network/events', get_network_events)
    app.router.add_get('/api/analytics/network/stats', get_network_stats)


async def analytics_notify(source: str, level: str, message: str):
    """
    Unified fan-out notifier for Analytics & Network events.
    Sends to Inbox/UI (process_incoming) and all outbound channels (Gotify, ntfy, email).
    """
    try:
        logger.info(f"Analytics notification: [{level}] {source}: {message}")

        # Import main notifier safely inside function
        from notify import process_incoming
        from bot import send_message
        try:
            from notify import broadcast_websocket
        except ImportError:
            broadcast_websocket = None

        # 1️⃣ Beautify + Inbox + Web UI
        await process_incoming({
            "source": source,
            "level": level,
            "message": message,
            "origin": "analytics"
        })

        # 2️⃣ External fan-out (Gotify / ntfy / email)
        title = f"Analytics: {source} [{level.upper()}]"
        send_message(title, message, priority=5)

        # 3️⃣ Live UI websocket broadcast (if active)
        if broadcast_websocket:
            await broadcast_websocket({
                "type": "analytics_event",
                "source": source,
                "level": level,
                "message": message
            })

    except Exception as e:
        logger.error(f"Analytics fan-out failed: {e}")




async def init_analytics(app: web.Application, notification_callback: Optional[Callable] = None):
    """Initialize analytics module"""
    global db, monitor, scanner
    
    db = AnalyticsDB()
    
    # Use provided callback or default
    callback = notification_callback or analytics_notify
    
    monitor = HealthMonitor(db, callback)
    scanner = NetworkScanner(db)
    scanner.set_notification_callback(callback)
    
    # Start monitoring all enabled services
    await monitor.start_all()
    
    logger.info("Analytics module initialized with network monitoring")


async def shutdown_analytics():
    """Shutdown analytics module"""
    if monitor:
        await monitor.stop_all()
    if scanner:
        await scanner.stop_monitoring()
    logger.info("Analytics module shutdown complete")
