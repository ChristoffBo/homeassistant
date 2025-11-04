#!/usr/bin/env python3
"""
Jarvis Prime - Analytics & Uptime Monitoring Module
aiohttp-compatible version for Jarvis Prime

VERSION: 2025-01-19-FINAL-FIX + SPEED TEST INTEGRATION

Complete file with Internet Speed Testing integrated
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
import socket

logger = logging.getLogger(__name__)

# Print version on import
logger.info("ðŸ”¥ Analytics Module VERSION: 2025-01-19-FINAL-FIX + SPEED TEST ðŸ”¥")


# Service fingerprint database - maps ports to common services
SERVICE_FINGERPRINTS = {
    # Media Management (Arr Stack)
    7878: {'name': 'Radarr', 'category': 'media', 'path': '/api/v3/system/status'},
    8989: {'name': 'Sonarr', 'category': 'media', 'path': '/api/v3/system/status'},
    8686: {'name': 'Lidarr', 'category': 'media', 'path': '/api/v1/system/status'},
    8787: {'name': 'Readarr', 'category': 'media', 'path': '/api/v1/system/status'},
    6767: {'name': 'Bazarr', 'category': 'media', 'path': '/api/system/status'},
    5055: {'name': 'Overseerr', 'category': 'media', 'path': '/api/v1/status'},
    5056: {'name': 'Jellyseerr', 'category': 'media', 'path': '/api/v1/status'},
    9696: {'name': 'Prowlarr', 'category': 'media', 'path': '/api/v1/system/status'},
    8191: {'name': 'FlareSolverr', 'category': 'media', 'path': '/'},
    8265: {'name': 'Tdarr', 'category': 'media', 'path': '/api/v2/status'},
    8266: {'name': 'Tdarr Server', 'category': 'media', 'path': '/api/v2/status'},
    
    # Download Clients
    8080: {'name': 'SABnzbd', 'category': 'download', 'path': '/api?mode=version'},
    9091: {'name': 'Transmission', 'category': 'download', 'path': '/transmission/rpc'},
    8112: {'name': 'Deluge', 'category': 'download', 'path': '/'},
    6881: {'name': 'qBittorrent', 'category': 'download', 'path': '/api/v2/app/version'},
    8081: {'name': 'NZBGet', 'category': 'download', 'path': '/'},
    9117: {'name': 'Jackett', 'category': 'download', 'path': '/api/v2.0/server/config'},
    5076: {'name': 'NZBHydra2', 'category': 'download', 'path': '/api/system/info'},
    
    # Media Servers
    32400: {'name': 'Plex', 'category': 'media-server', 'path': '/identity'},
    8096: {'name': 'Jellyfin', 'category': 'media-server', 'path': '/System/Info/Public'},
    8920: {'name': 'Emby', 'category': 'media-server', 'path': '/System/Info/Public'},
    8200: {'name': 'Tautulli', 'category': 'media-server', 'path': '/api/v2'},
    
    # Home Automation
    8123: {'name': 'Home Assistant', 'category': 'automation', 'path': '/api/'},
    1880: {'name': 'Node-RED', 'category': 'automation', 'path': '/'},
    8088: {'name': 'Domoticz', 'category': 'automation', 'path': '/json.htm'},
    8125: {'name': 'Zigbee2MQTT', 'category': 'automation', 'path': '/api/info'},
    
    # Monitoring & Management
    3001: {'name': 'Uptime Kuma', 'category': 'monitoring', 'path': '/api/status-page'},
    9000: {'name': 'Portainer', 'category': 'management', 'path': '/api/status'},
    19999: {'name': 'Netdata', 'category': 'monitoring', 'path': '/api/v1/info'},
    3000: {'name': 'Grafana', 'category': 'monitoring', 'path': '/api/health'},
    9090: {'name': 'Prometheus', 'category': 'monitoring', 'path': '/-/healthy'},
    8086: {'name': 'InfluxDB', 'category': 'monitoring', 'path': '/ping'},
    
    # Network Services & DNS
    53: {'name': 'DNS Server', 'category': 'network', 'path': None},
    80: {'name': 'HTTP Server', 'category': 'network', 'path': '/'},
    443: {'name': 'HTTPS Server', 'category': 'network', 'path': '/'},
    5335: {'name': 'Pi-hole', 'category': 'network', 'path': '/admin/api.php'},
    5300: {'name': 'AdGuard Home', 'category': 'network', 'path': '/control/status'},
    
    # VPN & Proxy
    8888: {'name': 'Gluetun', 'category': 'vpn', 'path': '/v1/publicip/ip'},
    8443: {'name': 'Nginx Proxy Manager', 'category': 'proxy', 'path': '/api/'},
    81: {'name': 'Nginx Proxy Manager', 'category': 'proxy', 'path': '/api/'},
    
    # Storage & Backup
    5000: {'name': 'Synology DSM', 'category': 'storage', 'path': '/'},
    5001: {'name': 'Synology DSM (HTTPS)', 'category': 'storage', 'path': '/'},
    9001: {'name': 'MinIO Console', 'category': 'storage', 'path': '/'},
    8200: {'name': 'Duplicati', 'category': 'backup', 'path': '/api/v1/serverstate'},
    5076: {'name': 'Syncthing', 'category': 'storage', 'path': '/rest/system/version'},
    8384: {'name': 'Syncthing', 'category': 'storage', 'path': '/rest/system/version'},
    
    # Databases
    3306: {'name': 'MySQL/MariaDB', 'category': 'database', 'path': None},
    5432: {'name': 'PostgreSQL', 'category': 'database', 'path': None},
    6379: {'name': 'Redis', 'category': 'database', 'path': None},
    27017: {'name': 'MongoDB', 'category': 'database', 'path': None},
}


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
    id: int = None  # Database ID


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


@dataclass
class SpeedTestResult:
    """Internet speed test result"""
    timestamp: int
    download: float  # Mbps
    upload: float    # Mbps
    ping: float      # milliseconds
    server: str
    jitter: Optional[float] = None
    packet_loss: Optional[float] = None
    status: str = 'normal'  # normal, degraded, offline


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
        
        # Internet speed test table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS network_speed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                download REAL NOT NULL,
                upload REAL NOT NULL,
                ping REAL NOT NULL,
                server TEXT,
                jitter REAL,
                packet_loss REAL,
                status TEXT DEFAULT 'normal'
            )
        """)
        
        # Speed test settings table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS speed_test_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                schedule_mode TEXT DEFAULT 'interval',
                interval_hours INTEGER DEFAULT 12,
                schedule_times TEXT DEFAULT '[]',
                degrade_threshold REAL DEFAULT 0.7,
                ping_threshold REAL DEFAULT 1.5,
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        # Insert default settings if not exists
        cur.execute("""
            INSERT OR IGNORE INTO speed_test_settings (id, schedule_mode, interval_hours, schedule_times)
            VALUES (1, 'interval', 12, '[]')
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
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_speed_timestamp 
            ON network_speed(timestamp DESC)
        """)
        
        # Migrate existing tables
        self._migrate_tables(cur)
        
        conn.commit()
        conn.close()
        logger.info("Analytics database initialized with network and speed test monitoring")
    
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
        
        except Exception as e:
            logger.error(f"Migration error: {e}")
    
    def add_service(self, service: HealthCheck):
        """Add or update a service"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO analytics_services 
            (service_name, endpoint, check_type, expected_status, timeout, check_interval, enabled, retries, flap_window, flap_threshold, suppression_duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            service.service_name,
            service.endpoint,
            service.check_type,
            service.expected_status,
            service.timeout,
            service.interval,
            int(service.enabled),
            service.retries,
            service.flap_window,
            service.flap_threshold,
            service.suppression_duration
        ))
        conn.commit()
        conn.close()
    
    def get_services(self) -> List[HealthCheck]:
        """Get all services"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM analytics_services")
        rows = cur.fetchall()
        conn.close()
        
        services = []
        for row in rows:
            row_dict = dict(row)
            service = HealthCheck(
                service_name=row_dict['service_name'],
                endpoint=row_dict['endpoint'],
                check_type=row_dict['check_type'],
                expected_status=row_dict['expected_status'],
                timeout=row_dict['timeout'],
                interval=row_dict['check_interval'],
                enabled=bool(row_dict['enabled']),
                retries=row_dict.get('retries', 3),
                flap_window=row_dict.get('flap_window', 3600),
                flap_threshold=row_dict.get('flap_threshold', 5),
                suppression_duration=row_dict.get('suppression_duration', 3600)
            )
            service.id = row_dict['id']
            services.append(service)
        return services
    
    def get_all_services(self) -> List[Dict]:
        """Get all configured services with current status and stats"""
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
                 ORDER BY timestamp DESC LIMIT 1) as last_check,
                (SELECT AVG(response_time) FROM analytics_metrics 
                 WHERE service_name = analytics_services.service_name 
                 AND timestamp > (strftime('%s', 'now') - 86400)
                 AND response_time IS NOT NULL) as avg_response_24h,
                (SELECT response_time FROM analytics_metrics 
                 WHERE service_name = analytics_services.service_name 
                 ORDER BY timestamp DESC LIMIT 1) as latest_response_time,
                (SELECT COUNT(*) FROM analytics_metrics 
                 WHERE service_name = analytics_services.service_name 
                 AND timestamp > (strftime('%s', 'now') - 86400)) as total_checks_24h,
                (SELECT COUNT(*) FROM analytics_metrics 
                 WHERE service_name = analytics_services.service_name 
                 AND status = 'up'
                 AND timestamp > (strftime('%s', 'now') - 86400)) as successful_checks_24h
            FROM analytics_services
            ORDER BY service_name
        """)
        
        services = [dict(row) for row in cur.fetchall()]
        
        for service in services:
            if service['total_checks_24h'] and service['total_checks_24h'] > 0:
                service['uptime_24h'] = round((service['successful_checks_24h'] / service['total_checks_24h']) * 100, 1)
            else:
                service['uptime_24h'] = 100.0 if service.get('current_status') == 'up' else 0.0
            
            if service['avg_response_24h'] is not None:
                service['avg_response'] = round(service['avg_response_24h'] * 1000, 1)
            elif service['latest_response_time'] is not None:
                service['avg_response'] = round(service['latest_response_time'] * 1000, 1)
            else:
                service['avg_response'] = None
            
            if 'latest_response_time' in service:
                del service['latest_response_time']
        
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
    
    def add_metric(self, metric: ServiceMetric):
        """Record a health check result"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO analytics_metrics (service_name, timestamp, status, response_time, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (metric.service_name, metric.timestamp, metric.status, metric.response_time, metric.error_message))
        conn.commit()
        conn.close()
    
    def get_metrics(self, service_name: str, hours: int = 24) -> List[ServiceMetric]:
        """Get recent metrics for a service"""
        cutoff = int(time.time()) - (hours * 3600)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM analytics_metrics 
            WHERE service_name = ? AND timestamp > ?
            ORDER BY timestamp DESC
        """, (service_name, cutoff))
        rows = cur.fetchall()
        conn.close()
        
        return [ServiceMetric(
            service_name=row['service_name'],
            timestamp=row['timestamp'],
            status=row['status'],
            response_time=row['response_time'],
            error_message=row['error_message']
        ) for row in rows]
    
    def get_all_metrics(self, hours: int = 24) -> List[ServiceMetric]:
        """Get all metrics across all services"""
        cutoff = int(time.time()) - (hours * 3600)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM analytics_metrics 
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """, (cutoff,))
        rows = cur.fetchall()
        conn.close()
        
        return [ServiceMetric(
            service_name=row['service_name'],
            timestamp=row['timestamp'],
            status=row['status'],
            response_time=row['response_time'],
            error_message=row['error_message']
        ) for row in rows]
    
    def create_incident(self, service_name: str, error_message: str = None):
        """Create a new incident"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO analytics_incidents (service_name, start_time, error_message)
            VALUES (?, ?, ?)
        """, (service_name, int(time.time()), error_message))
        conn.commit()
        conn.close()
    
    def resolve_incident(self, service_name: str):
        """Resolve the most recent incident for a service"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, start_time FROM analytics_incidents 
            WHERE service_name = ? AND status = 'ongoing'
            ORDER BY start_time DESC
            LIMIT 1
        """, (service_name,))
        
        row = cur.fetchone()
        if row:
            incident_id, start_time = row
            end_time = int(time.time())
            duration = end_time - start_time
            
            cur.execute("""
                UPDATE analytics_incidents 
                SET end_time = ?, duration = ?, status = 'resolved'
                WHERE id = ?
            """, (end_time, duration, incident_id))
            
            conn.commit()
        
        conn.close()
    
    def get_incidents(self, service_name: Optional[str] = None, hours: int = 168) -> Dict[str, List[Dict]]:
        """Get recent incidents"""
        cutoff = int(time.time()) - (hours * 3600)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        if service_name:
            cur.execute("""
                SELECT * FROM analytics_incidents 
                WHERE service_name = ? AND start_time > ?
                ORDER BY start_time DESC
            """, (service_name, cutoff))
        else:
            cur.execute("""
                SELECT * FROM analytics_incidents 
                WHERE start_time > ?
                ORDER BY start_time DESC
            """, (cutoff,))
        
        rows = cur.fetchall()
        conn.close()
        
        incidents = []
        for row in rows:
            incidents.append({
                'id': row['id'],
                'service_name': row['service_name'],
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'duration': row['duration'],
                'status': row['status'],
                'error_message': row['error_message']
            })
        
        return {"incidents": incidents}
    
    def purge_old_metrics(self, days: int = 30):
        """Delete metrics older than specified days"""
        cutoff = int(time.time()) - (days * 86400)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM analytics_metrics WHERE timestamp < ?", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def purge_old_incidents(self, days: int = 90):
        """Delete incidents older than specified days"""
        cutoff = int(time.time()) - (days * 86400)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM analytics_incidents WHERE start_time < ?", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def purge_speed_tests(self, days: int = 30):
        """Delete speed tests older than specified days"""
        cutoff = int(time.time()) - (days * 86400)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM network_speed WHERE timestamp < ?", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def reset_service_metrics(self, service_name: str):
        """Delete all metrics for a specific service"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM analytics_metrics WHERE service_name = ?", (service_name,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def reset_service_incidents(self, service_name: str):
        """Delete all incidents for a specific service"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM analytics_incidents WHERE service_name = ?", (service_name,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    # Network device methods
    
    def add_or_update_device(self, device: NetworkDevice):
        """Add or update a network device"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        now = int(time.time())
        
        cur.execute("SELECT first_seen FROM network_devices WHERE mac_address = ?", (device.mac_address,))
        row = cur.fetchone()
        
        if row:
            cur.execute("""
                UPDATE network_devices 
                SET ip_address = ?, hostname = ?, vendor = ?, last_seen = ?, updated_at = ?
                WHERE mac_address = ?
            """, (device.ip_address, device.hostname, device.vendor, now, now, device.mac_address))
        else:
            cur.execute("""
                INSERT INTO network_devices 
                (mac_address, ip_address, hostname, vendor, first_seen, last_seen, is_permanent, is_monitored)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device.mac_address,
                device.ip_address,
                device.hostname,
                device.vendor,
                device.first_seen or now,
                now,
                int(device.is_permanent),
                int(device.is_monitored)
            ))
        
        conn.commit()
        conn.close()
    
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
    
    def get_devices(self) -> List[NetworkDevice]:
        """Get all network devices"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM network_devices ORDER BY last_seen DESC")
        rows = cur.fetchall()
        conn.close()
        
        devices = []
        for row in rows:
            devices.append(NetworkDevice(
                mac_address=row['mac_address'],
                ip_address=row['ip_address'],
                hostname=row['hostname'],
                vendor=row['vendor'],
                custom_name=row['custom_name'],
                first_seen=row['first_seen'],
                last_seen=row['last_seen'],
                is_permanent=bool(row['is_permanent']),
                is_monitored=bool(row['is_monitored'])
            ))
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
            params.append(custom_name if custom_name and custom_name.strip() else None)
        
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
    
    def add_network_event(self, event_type: str, mac_address: str, ip_address: str = None, hostname: str = None):
        """Add a network event"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO network_events (event_type, mac_address, ip_address, hostname, timestamp)
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
    
    def mark_event_notified(self, event_id: int):
        """Mark an event as notified"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("UPDATE network_events SET notified = 1 WHERE id = ?", (event_id,))
        conn.commit()
        conn.close()
    
    def get_network_stats(self) -> Dict:
        """Get network monitoring statistics"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) as total FROM network_devices")
        total = cur.fetchone()['total']
        
        cur.execute("SELECT COUNT(*) as monitored FROM network_devices WHERE is_monitored = 1")
        monitored = cur.fetchone()['monitored']
        
        cur.execute("SELECT COUNT(*) as permanent FROM network_devices WHERE is_permanent = 1")
        permanent = cur.fetchone()['permanent']
        
        cur.execute("""
            SELECT COUNT(*) as scan_count 
            FROM network_scans 
            WHERE scan_timestamp > ?
        """, (int(time.time()) - 86400,))
        scans_24h = cur.fetchone()['scan_count']
        
        cur.execute("""
            SELECT COUNT(*) as event_count 
            FROM network_events 
            WHERE timestamp > ?
        """, (int(time.time()) - 86400,))
        events_24h = cur.fetchone()['event_count']
        
        cutoff = int(time.time()) - 86400
        cur.execute("SELECT COUNT(*) FROM network_devices WHERE last_seen > ?", (cutoff,))
        active_24h = cur.fetchone()[0]
        
        cur.execute("""
            SELECT MAX(scan_timestamp) as last_scan 
            FROM network_scans
        """)
        last_scan_row = cur.fetchone()
        last_scan = last_scan_row['last_scan'] if last_scan_row else None
        
        conn.close()
        
        return {
            'total_devices': total,
            'monitored_devices': monitored,
            'permanent_devices': permanent,
            'active_24h': active_24h,
            'scans_24h': scans_24h,
            'events_24h': events_24h,
            'last_scan': last_scan
        }
    
    def check_ip_in_services(self, ip_address: str) -> bool:
        """Check if IP address already exists in analytics services"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT COUNT(*) as count
            FROM analytics_services
            WHERE endpoint LIKE ?
        """, (f'%{ip_address}%',))
        
        result = cur.fetchone()
        conn.close()
        
        return result[0] > 0
    
    # Speed test methods
    
    def record_speed_test(self, result: SpeedTestResult):
        """Record speed test result"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO network_speed 
            (timestamp, download, upload, ping, server, jitter, packet_loss, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.timestamp,
            result.download,
            result.upload,
            result.ping,
            result.server,
            result.jitter,
            result.packet_loss,
            result.status
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"Speed test recorded: {result.download:.1f}/{result.upload:.1f} Mbps, {result.ping:.1f}ms")
    
    def get_speed_test_history(self, hours: int = 168) -> List[Dict]:
        """Get speed test history (default 7 days)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cutoff = int(time.time()) - (hours * 3600)
        
        cur.execute("""
            SELECT * FROM network_speed 
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """, (cutoff,))
        
        rows = cur.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_speed_test_averages(self, last_n: int = 5) -> Dict[str, float]:
        """Get rolling averages for last N tests"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                AVG(download) as avg_download,
                AVG(upload) as avg_upload,
                AVG(ping) as avg_ping
            FROM (
                SELECT download, upload, ping 
                FROM network_speed 
                ORDER BY timestamp DESC 
                LIMIT ?
            )
        """, (last_n,))
        
        row = cur.fetchone()
        conn.close()
        
        if not row or not row[0]:
            return {'avg_download': 0, 'avg_upload': 0, 'avg_ping': 0}
        
        return {
            'avg_download': round(row[0], 2),
            'avg_upload': round(row[1], 2),
            'avg_ping': round(row[2], 2)
        }
    
    def get_latest_speed_test(self) -> Optional[Dict]:
        """Get most recent speed test"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM network_speed 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        row = cur.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def update_speed_test_status(self, timestamp: int, status: str):
        """Update status of a speed test"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE network_speed 
            SET status = ?
            WHERE timestamp = ?
        """, (status, timestamp))
        
        conn.commit()
        conn.close()
    
    def get_speed_test_stats(self) -> Dict:
        """Get speed test statistics"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM network_speed")
        total_tests = cur.fetchone()[0]
        
        cur.execute("SELECT MAX(timestamp) FROM network_speed")
        last_test_row = cur.fetchone()
        last_test = last_test_row[0] if last_test_row else None
        
        cur.execute("""
            SELECT 
                AVG(download) as avg_download,
                AVG(upload) as avg_upload,
                AVG(ping) as avg_ping
            FROM network_speed
        """)
        row = cur.fetchone()
        
        conn.close()
        
        return {
            'total_tests': total_tests,
            'last_test': last_test,
            'avg_download': round(row[0], 2) if row and row[0] else 0,
            'avg_upload': round(row[1], 2) if row and row[1] else 0,
            'avg_ping': round(row[2], 2) if row and row[2] else 0
        }
    
    def get_speed_test_settings(self) -> Dict:
        """Get speed test schedule settings"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("SELECT * FROM speed_test_settings WHERE id = 1")
        row = cur.fetchone()
        conn.close()
        
        if row:
            return {
                'schedule_mode': row['schedule_mode'],
                'interval_hours': row['interval_hours'],
                'schedule_times': json.loads(row['schedule_times']),
                'degrade_threshold': row['degrade_threshold'],
                'ping_threshold': row['ping_threshold']
            }
        else:
            return {
                'schedule_mode': 'interval',
                'interval_hours': 12,
                'schedule_times': [],
                'degrade_threshold': 0.7,
                'ping_threshold': 1.5
            }
    
    def update_speed_test_settings(self, settings: Dict):
        """Update speed test schedule settings"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        schedule_times_json = json.dumps(settings.get('schedule_times', []))
        
        cur.execute("""
            UPDATE speed_test_settings 
            SET schedule_mode = ?,
                interval_hours = ?,
                schedule_times = ?,
                degrade_threshold = ?,
                ping_threshold = ?,
                updated_at = ?
            WHERE id = 1
        """, (
            settings.get('schedule_mode', 'interval'),
            settings.get('interval_hours', 12),
            schedule_times_json,
            settings.get('degrade_threshold', 0.7),
            settings.get('ping_threshold', 1.5),
            int(time.time())
        ))
        
        conn.commit()
        conn.close()


# ============================================================================
# HEALTH MONITOR CLASS
# ============================================================================

class HealthMonitor:
    """Service health monitoring with retry and flap protection"""
    
    def __init__(self, db: AnalyticsDB, notification_callback: Callable):
        self.db = db
        self.notify = notification_callback
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.flap_trackers: Dict[str, FlapTracker] = {}
    
      async def check_service(self, service: HealthCheck) -> ServiceMetric:
        """Perform a single health check with retry logic and robust aiohttp handling"""
        start_time = time.time()

        for attempt in range(service.retries):
            try:
                # -----------------------------
                # HTTP / HTTPS service check
                # -----------------------------
                if service.check_type == 'http':
                    async with aiohttp.ClientSession() as session:
                        try:
                            async with session.get(
                                service.endpoint,
                                timeout=aiohttp.ClientTimeout(total=service.timeout)
                            ) as response:
                                response_time = time.time() - start_time
                                if response.status == service.expected_status:
                                    return ServiceMetric(
                                        service_name=service.service_name,
                                        timestamp=int(time.time()),
                                        status='up',
                                        response_time=response_time
                                    )
                                else:
                                    error_msg = f"Unexpected status {response.status} (expected {service.expected_status})"
                        except asyncio.TimeoutError:
                            error_msg = f"HTTP timeout after {service.timeout}s"
                        except aiohttp.ClientError as e:
                            error_msg = f"HTTP error: {str(e)}"

                # -----------------------------
                # TCP port check
                # -----------------------------
                elif service.check_type == 'tcp':
                    try:
                        host, port = service.endpoint.split(':')
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, int(port)),
                            timeout=service.timeout
                        )
                        writer.close()
                        await writer.wait_closed()
                        response_time = time.time() - start_time
                        return ServiceMetric(
                            service_name=service.service_name,
                            timestamp=int(time.time()),
                            status='up',
                            response_time=response_time
                        )
                    except Exception as e:
                        error_msg = f"TCP connection failed: {str(e)}"

                # -----------------------------
                # Ping check
                # -----------------------------
                elif service.check_type == 'ping':
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            'ping', '-c', '1', '-W', str(service.timeout), service.endpoint,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=service.timeout + 1)
                        response_time = time.time() - start_time

                        if proc.returncode == 0:
                            return ServiceMetric(
                                service_name=service.service_name,
                                timestamp=int(time.time()),
                                status='up',
                                response_time=response_time
                            )
                        else:
                            error_msg = f"Ping failed ({stderr.decode().strip() or 'no reply'})"
                    except asyncio.TimeoutError:
                        error_msg = f"Ping timeout after {service.timeout}s"
                    except Exception as e:
                        error_msg = f"Ping error: {str(e)}"

                # -----------------------------
                # Retry or final failure
                # -----------------------------
                if attempt < service.retries - 1:
                    await asyncio.sleep(1)
                    continue

                return ServiceMetric(
                    service_name=service.service_name,
                    timestamp=int(time.time()),
                    status='down',
                    response_time=time.time() - start_time,
                    error_message=error_msg
                )

            except Exception as e:
                if attempt < service.retries - 1:
                    await asyncio.sleep(1)
                    continue
                return ServiceMetric(
                    service_name=service.service_name,
                    timestamp=int(time.time()),
                    status='down',
                    response_time=time.time() - start_time,
                    error_message=f"General error: {str(e)}"
                )

        )
    
    def should_suppress_notification(self, service_name: str, status: str) -> bool:
        """Check if notification should be suppressed due to flapping"""
        if service_name not in self.flap_trackers:
            self.flap_trackers[service_name] = FlapTracker()
        
        tracker = self.flap_trackers[service_name]
        now = time.time()
        
        if tracker.suppressed_until and now < tracker.suppressed_until:
            return True
        
        if tracker.last_status == status:
            return False
        
        tracker.flap_times.append(now)
        tracker.last_status = status
        
        service = None
        for s in self.db.get_services():
            if s.service_name == service_name:
                service = s
                break
        
        if not service:
            return False
        
        while tracker.flap_times and now - tracker.flap_times[0] > service.flap_window:
            tracker.flap_times.popleft()
        
        if len(tracker.flap_times) >= service.flap_threshold:
            tracker.suppressed_until = now + service.suppression_duration
            logger.warning(f"Flapping detected for {service_name}, suppressing notifications for {service.suppression_duration}s")
            return True
        
        return False
    
    async def monitor_service(self, service: HealthCheck):
        """Continuously monitor a service"""
        logger.info(f"Starting monitor for {service.service_name}")
        
        while True:
            try:
                if not service.enabled:
                    await asyncio.sleep(service.interval)
                    continue
                
                metric = await self.check_service(service)
                self.db.add_metric(metric)
                
                recent_metrics = self.db.get_metrics(service.service_name, hours=1)
                previous_status = recent_metrics[1].status if len(recent_metrics) > 1 else None
                
                if metric.status == 'down' and previous_status != 'down':
                    self.db.create_incident(service.service_name, metric.error_message)
                    
                    if not self.should_suppress_notification(service.service_name, 'down'):
                        await analytics_notify(
                            service.service_name,
                            'down',
                            f"Service is DOWN: {metric.error_message or 'No response'}"
                        )
                
                elif metric.status == 'up' and previous_status == 'down':
                    self.db.resolve_incident(service.service_name)
                    
                    if not self.should_suppress_notification(service.service_name, 'up'):
                        await analytics_notify(
                            service.service_name,
                            'up',
                            f"Service has RECOVERED (response time: {metric.response_time:.2f}s)"
                        )
                
                await asyncio.sleep(service.interval)
                
            except asyncio.CancelledError:
                logger.info(f"Monitor cancelled for {service.service_name}")
                break
            except Exception as e:
                logger.error(f"Error monitoring {service.service_name}: {e}")
                await asyncio.sleep(service.interval)
    
    async def start_all(self):
        """Start monitoring all enabled services"""
        services = self.db.get_services()
        for service in services:
            if service.enabled and service.service_name not in self.monitoring_tasks:
                task = asyncio.create_task(self.monitor_service(service))
                self.monitoring_tasks[service.service_name] = task
    
    async def stop_all(self):
        """Stop all monitoring tasks"""
        for task in self.monitoring_tasks.values():
            task.cancel()
        await asyncio.gather(*self.monitoring_tasks.values(), return_exceptions=True)
        self.monitoring_tasks.clear()


# ============================================================================
# NETWORK SCANNER CLASS
# ============================================================================

class NetworkScanner:
    """Network device discovery and monitoring"""
    
    def __init__(self, db: AnalyticsDB):
        self.db = db
        self.monitoring = False
        self.alert_new_devices = True
        self.notification_callback = None
        self._monitor_task = None
    
    def set_notification_callback(self, callback: Callable):
        """Set the notification callback for network events"""
        self.notification_callback = callback
    
    async def scan_network(self) -> List[NetworkDevice]:
        """Scan local network for devices using ARP"""
        start_time = time.time()
        devices = []
        
        try:
            proc = await asyncio.create_subprocess_exec(
                'arp', '-a',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error(f"ARP scan failed: {stderr.decode()}")
                return devices
            
            output = stdout.decode()
            
            for line in output.split('\n'):
                match = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)', line)
                if match:
                    ip = match.group(1)
                    mac = match.group(2).upper()
                    
                    if mac == 'FF:FF:FF:FF:FF:FF' or mac.startswith('00:00:00'):
                        continue
                    
                    hostname = await self._resolve_hostname(ip)
                    vendor = self._lookup_vendor(mac)
                    
                    device = NetworkDevice(
                        mac_address=mac,
                        ip_address=ip,
                        hostname=hostname,
                        vendor=vendor,
                        first_seen=int(time.time()),
                        last_seen=int(time.time())
                    )
                    devices.append(device)
            
            scan_duration = time.time() - start_time
            self.db.record_scan(len(devices), scan_duration)
            
            logger.info(f"Network scan complete: {len(devices)} devices found in {scan_duration:.2f}s")
            
        except Exception as e:
            logger.error(f"Network scan error: {e}")
        
        return devices
    
    async def _resolve_hostname(self, ip: str) -> Optional[str]:
        """Resolve hostname from IP address"""
        try:
            loop = asyncio.get_event_loop()
            hostname = await asyncio.wait_for(
                loop.run_in_executor(None, socket.gethostbyaddr, ip),
                timeout=2.0
            )
            return hostname[0] if hostname else None
        except:
            return None
    
    def _lookup_vendor(self, mac: str) -> Optional[str]:
        """Lookup vendor from MAC address OUI (first 3 octets)"""
        oui = mac[:8].replace(':', '').upper()
        
        vendors = {
            '001B63': 'Apple',
            '0050F2': 'Microsoft',
            '00D0CA': 'Cisco',
            'B827EB': 'Raspberry Pi',
            'DCA632': 'Raspberry Pi',
            'E45F01': 'Raspberry Pi',
            '001DD8': 'Synology',
            '001132': 'Synology',
            '0011D8': 'Synology',
            '8086F2': 'Intel',
            '9CFCE8': 'Intel',
            '001EC0': 'Samsung',
            '002454': 'Samsung',
        }
        
        return vendors.get(oui[:6], None)
    
    async def update_device_status(self):
        """Scan network and update device statuses"""
        current_devices = await self.scan_network()
        known_devices = self.db.get_devices()
        
        current_macs = {d.mac_address for d in current_devices}
        known_macs = {d.mac_address for d in known_devices}
        
        for device in current_devices:
            existing = self.db.get_device(device.mac_address)
            
            if not existing:
                self.db.add_or_update_device(device)
                self.db.record_network_event('new_device', device.mac_address, device.ip_address, device.hostname)
                
                if self.alert_new_devices:
                    await self._notify_new_device(device)
            else:
                self.db.add_or_update_device(device)
                
                was_offline = (time.time() - existing.get('last_seen', 0)) > 300
                if was_offline and existing.get('is_monitored'):
                    self.db.record_network_event('device_online', device.mac_address, device.ip_address, device.hostname)
                    await self._notify_device_online(device)
        
        for known_device in known_devices:
            if known_device.mac_address not in current_macs:
                if known_device.is_monitored:
                    time_since_seen = time.time() - known_device.last_seen
                    if time_since_seen > 300 and time_since_seen < 600:
                        self.db.record_network_event('device_offline', known_device.mac_address, known_device.ip_address, known_device.hostname)
                        await self._notify_device_offline(known_device)
    
    async def _notify_new_device(self, device: NetworkDevice):
        """Send notification for new device"""
        name = device.custom_name or device.hostname or device.ip_address
        vendor_info = f" ({device.vendor})" if device.vendor else ""
        
        await analytics_notify(
            'Network Monitor',
            'info',
            f"ðŸ†• New device: {name}{vendor_info}\nMAC: {device.mac_address}\nIP: {device.ip_address}"
        )
    
    async def _notify_device_offline(self, device: NetworkDevice):
        """Send notification for device going offline"""
        name = device.custom_name or device.hostname or device.ip_address
        
        await analytics_notify(
            'Network Monitor',
            'warning',
            f"âš ï¸ Device offline: {name}\nMAC: {device.mac_address}"
        )
    
    async def _notify_device_online(self, device: NetworkDevice):
        """Send notification for device coming back online"""
        name = device.custom_name or device.hostname or device.ip_address
        
        await analytics_notify(
            'Network Monitor',
            'info',
            f"âœ… Device online: {name}\nIP: {device.ip_address}"
        )
    
    async def monitor_loop(self):
        """Continuous network monitoring loop"""
        while self.monitoring:
            try:
                await self.update_device_status()
                await asyncio.sleep(300)  # Scan every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Network monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def start_monitoring(self):
        """Start continuous network monitoring"""
        if self.monitoring:
            return
        
        self.monitoring = True
        self._monitor_task = asyncio.create_task(self.monitor_loop())
        logger.info("Network monitoring started")
    
    async def stop_monitoring(self):
        """Stop continuous network monitoring"""
        if not self.monitoring:
            return
        
        self.monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Network monitoring stopped")


# ============================================================================
# SPEED TEST MONITOR CLASS
# ============================================================================

class SpeedTestMonitor:
    """Internet speed testing and monitoring"""
    
    def __init__(self, db: AnalyticsDB):
        self.db = db
        self.monitoring = False
        self.testing = False
        self.schedule_mode = 'interval'
        self.interval_hours = 12
        self.schedule_times = []
        self.degrade_threshold = 0.7
        self.ping_threshold = 1.5
        self.consecutive_failures = 0
        self.notification_callback = None
        self._monitor_task = None
        self._load_settings()
    
    def _load_settings(self):
        """Load settings from database"""
        try:
            settings = self.db.get_speed_test_settings()
            self.schedule_mode = settings['schedule_mode']
            self.interval_hours = settings['interval_hours']
            self.schedule_times = settings['schedule_times']
            self.degrade_threshold = settings['degrade_threshold']
            self.ping_threshold = settings['ping_threshold']
            logger.info(f"Loaded speed test settings: mode={self.schedule_mode}, interval={self.interval_hours}h, times={self.schedule_times}")
        except Exception as e:
            logger.error(f"Failed to load speed test settings: {e}")
    
    def set_notification_callback(self, callback: Callable):
        """Set the notification callback"""
        self.notification_callback = callback
    
    async def run_speedtest(self) -> Optional[SpeedTestResult]:
        """Run a speed test using speedtest-cli"""
        if self.testing:
            logger.warning("Speed test already in progress")
            return None
        
        self.testing = True
        logger.info("Starting internet speed test...")
        
        try:
            # Check if speedtest-cli is installed
            proc = await asyncio.create_subprocess_exec(
                'which', 'speedtest',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            
            if proc.returncode != 0:
                logger.error("speedtest-cli not installed. Install with: pip install speedtest-cli")
                return None
            
            # Run speed test
            proc = await asyncio.create_subprocess_exec(
                'speedtest', '--format=json', '--accept-license', '--accept-gdpr',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            
            if proc.returncode != 0:
                logger.error(f"Speed test failed: {stderr.decode()}")
                self.consecutive_failures += 1
                
                if self.consecutive_failures >= 3:
                    await self._notify_offline()
                
                return None
            
            # Parse JSON
            result = json.loads(stdout.decode())
            
            download_mbps = result['download']['bandwidth'] / 125000
            upload_mbps = result['upload']['bandwidth'] / 125000
            ping_ms = result['ping']['latency']
            server_name = f"{result['server']['name']} ({result['server']['location']})"
            jitter_ms = result['ping'].get('jitter', None)
            packet_loss = result.get('packetLoss', None)
            
            speed_result = SpeedTestResult(
                timestamp=int(time.time()),
                download=round(download_mbps, 2),
                upload=round(upload_mbps, 2),
                ping=round(ping_ms, 2),
                server=server_name,
                jitter=round(jitter_ms, 2) if jitter_ms else None,
                packet_loss=round(packet_loss, 2) if packet_loss else None
            )
            
            self.consecutive_failures = 0
            self.db.record_speed_test(speed_result)
            await self._analyze_and_notify(speed_result)
            
            logger.info(f"Speed test complete: â†“{download_mbps:.1f} Mbps â†‘{upload_mbps:.1f} Mbps {ping_ms:.1f}ms")
            
            return speed_result
            
        except asyncio.TimeoutError:
            logger.error("Speed test timed out")
            self.consecutive_failures += 1
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Speed test error: {e}", exc_info=True)
            self.consecutive_failures += 1
            return None
        finally:
            self.testing = False
    
    async def _analyze_and_notify(self, result: SpeedTestResult):
        """Compare result to average and notify"""
        averages = self.db.get_speed_test_averages(last_n=5)
        
        if not averages or averages['avg_download'] == 0:
            await analytics_notify(
                'Internet Monitor',
                'info',
                f"Speed test: â†“{result.download} Mbps â†‘{result.upload} Mbps {result.ping}ms"
            )
            return
        
        # Calculate variance
        down_var = ((result.download - averages['avg_download']) / averages['avg_download']) * 100
        up_var = ((result.upload - averages['avg_upload']) / averages['avg_upload']) * 100
        ping_var = ((result.ping - averages['avg_ping']) / averages['avg_ping']) * 100
        
        # Check degradation
        is_degraded = False
        issues = []
        
        if result.download < (averages['avg_download'] * self.degrade_threshold):
            is_degraded = True
            issues.append(f"Download â†“{abs(down_var):.0f}% ({result.download:.1f} vs {averages['avg_download']:.1f} Mbps)")
        
        if result.upload < (averages['avg_upload'] * self.degrade_threshold):
            is_degraded = True
            issues.append(f"Upload â†“{abs(up_var):.0f}% ({result.upload:.1f} vs {averages['avg_upload']:.1f} Mbps)")
        
        if result.ping > (averages['avg_ping'] * self.ping_threshold):
            is_degraded = True
            issues.append(f"Latency â†‘{abs(ping_var):.0f}% ({result.ping:.1f} vs {averages['avg_ping']:.1f}ms)")
        
        if is_degraded:
            self.db.update_speed_test_status(result.timestamp, 'degraded')
            message = "ðŸš¨ Internet Degraded\n\n" + "\n".join(issues)
            await analytics_notify('Internet Monitor', 'warning', message)
        else:
            # Check recovery
            recent = self.db.get_speed_test_history(hours=24)
            if recent and len(recent) > 1:
                if recent[1].get('status') == 'degraded':
                    await analytics_notify(
                        'Internet Monitor',
                        'info',
                        f"âœ… Internet recovered\n\nâ†“{result.download:.1f} Mbps â†‘{result.upload:.1f} Mbps {result.ping:.1f}ms"
                    )
            
            # Normal notification
            variance_msg = ""
            if abs(down_var) > 5 or abs(up_var) > 5:
                variance_msg = f"\n\nDownload: {down_var:+.0f}%\nUpload: {up_var:+.0f}%\nPing: {ping_var:+.0f}%"
            
            await analytics_notify(
                'Internet Monitor',
                'info',
                f"ðŸŒ Speed Test\n\nâ†“{result.download:.1f} Mbps â†‘{result.upload:.1f} Mbps {result.ping:.1f}ms{variance_msg}"
            )
    
    async def _notify_offline(self):
        """Offline notification"""
        await analytics_notify(
            'Internet Monitor',
            'critical',
            f"ðŸ”´ Internet OFFLINE\n\n{self.consecutive_failures} consecutive failures"
        )
    
    async def monitor_loop(self):
        """Monitoring loop - supports both interval and scheduled modes"""
        logger.info(f"Speed test monitoring started in {self.schedule_mode} mode")
        
        while self.monitoring:
            try:
                if self.schedule_mode == 'interval':
                    # Interval mode - run test then wait
                    await self.run_speedtest()
                    wait_seconds = self.interval_hours * 3600
                    logger.info(f"Next speed test in {self.interval_hours}h")
                    await asyncio.sleep(wait_seconds)
                    
                elif self.schedule_mode == 'scheduled':
                    # Scheduled mode - check if it's time to run
                    if not self.schedule_times:
                        logger.warning("No scheduled times configured, waiting 5 minutes")
                        await asyncio.sleep(300)
                        continue
                    
                    from datetime import datetime
                    now = datetime.now()
                    current_time = now.strftime("%H:%M")
                    
                    # Check if current time matches any scheduled time
                    should_run = False
                    for scheduled_time in self.schedule_times:
                        if current_time == scheduled_time:
                            should_run = True
                            break
                    
                    if should_run:
                        logger.info(f"Running scheduled speed test at {current_time}")
                        await self.run_speedtest()
                        # Sleep for 61 seconds to avoid running twice in the same minute
                        await asyncio.sleep(61)
                    else:
                        # Check every 30 seconds
                        await asyncio.sleep(30)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(300)
    
    async def start_monitoring(self, settings: Dict = None):
        """Start monitoring with optional settings update"""
        if self.monitoring:
            return
        
        # Update settings if provided
        if settings:
            self.schedule_mode = settings.get('schedule_mode', self.schedule_mode)
            self.interval_hours = settings.get('interval_hours', self.interval_hours)
            self.schedule_times = settings.get('schedule_times', self.schedule_times)
            self.degrade_threshold = settings.get('degrade_threshold', self.degrade_threshold)
            self.ping_threshold = settings.get('ping_threshold', self.ping_threshold)
            
            # Save to database
            self.db.update_speed_test_settings({
                'schedule_mode': self.schedule_mode,
                'interval_hours': self.interval_hours,
                'schedule_times': self.schedule_times,
                'degrade_threshold': self.degrade_threshold,
                'ping_threshold': self.ping_threshold
            })
        else:
            # Reload from database
            self._load_settings()
        
        self.monitoring = True
        self._monitor_task = asyncio.create_task(self.monitor_loop())
        
        if self.schedule_mode == 'interval':
            logger.info(f"Speed test monitoring started ({self.interval_hours}h interval)")
        else:
            logger.info(f"Speed test monitoring started (scheduled at {self.schedule_times})")
    
    async def stop_monitoring(self):
        """Stop monitoring"""
        if not self.monitoring:
            return
        
        self.monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Speed test monitoring stopped")


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

db: Optional[AnalyticsDB] = None
monitor: Optional[HealthMonitor] = None
scanner: Optional[NetworkScanner] = None
speed_monitor: Optional[SpeedTestMonitor] = None


# ============================================================================
# NOTIFICATION HELPER
# ============================================================================

async def analytics_notify(service_name: str, severity: str, message: str):
    """Send notification via process_incoming (with Gotify fallback)"""
    # Try process_incoming for fan-out first
    try:
        from bot import process_incoming
        title = f'[Analytics] {service_name}'
        priority_map = {'info': 5, 'up': 5, 'warning': 7, 'down': 8, 'critical': 10}
        priority = priority_map.get(severity, 5)
        process_incoming(title, message, source="analytics", priority=priority)
        logger.debug(f"Notification sent via process_incoming: {title}")
        return
    except Exception as e:
        logger.debug(f"process_incoming not available: {e}, falling back to Gotify")
    
    # Fallback to Gotify
    try:
        import os
        gotify_url = os.getenv('GOTIFY_URL')
        gotify_token = os.getenv('GOTIFY_TOKEN')
        
        if not gotify_url or not gotify_token:
            logger.debug("Gotify not configured, skipping notification")
            return
        
        priority_map = {
            'info': 5,
            'up': 5,
            'warning': 7,
            'down': 8,
            'critical': 10
        }
        
        priority = priority_map.get(severity, 5)
        
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{gotify_url}/message",
                json={
                    'title': f'[Analytics] {service_name}',
                    'message': message,
                    'priority': priority
                },
                headers={'X-Gotify-Key': gotify_token},
                timeout=aiohttp.ClientTimeout(total=5)
            )
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


# ============================================================================
# API ROUTES - SERVICE MANAGEMENT
# ============================================================================

def _json(data: dict, status: int = 200):
    """Helper to return JSON response"""
    return web.json_response(data, status=status)

async def get_health_score(request: web.Request):
    """Get overall health score"""
    services = db.get_all_services()
    
    if not services:
        return _json({
            'health_score': 100,
            'total_services': 0,
            'up_services': 0,
            'down_services': 0
        })
    
    up_count = sum(1 for s in services if s.get('current_status') == 'up')
    total = len(services)
    
    health_score = round((up_count / total) * 100, 1) if total > 0 else 100
    
    return _json({
        'health_score': health_score,
        'total_services': total,
        'up_services': up_count,
        'down_services': total - up_count
    })

async def list_services(request: web.Request):
    """List all configured services"""
    services = db.get_all_services()
    return _json(services)

async def get_service(request: web.Request):
    """Get a specific service"""
    service_id = int(request.match_info['service_id'])
    service = db.get_service(service_id)
    
    if not service:
        return _json({'error': 'Service not found'}, status=404)
    
    return _json(service)

async def add_service(request: web.Request):
    """Add a new service"""
    try:
        data = await request.json()
    except:
        return _json({'error': 'Invalid JSON'}, status=400)
    
    required = ['service_name', 'endpoint', 'check_type']
    if not all(k in data for k in required):
        return _json({'error': 'Missing required fields'}, status=400)
    
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
    
    if service.enabled:
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({'success': True, 'service': service.service_name})

async def update_service(request: web.Request):
    """Update an existing service"""
    service_id = int(request.match_info['service_id'])
    
    try:
        data = await request.json()
    except:
        return _json({'error': 'Invalid JSON'}, status=400)
    
    existing = db.get_service(service_id)
    if not existing:
        return _json({'error': 'Service not found'}, status=404)
    
    service = HealthCheck(
        service_name=data.get('service_name', existing['service_name']),
        endpoint=data.get('endpoint', existing['endpoint']),
        check_type=data.get('check_type', existing['check_type']),
        expected_status=data.get('expected_status', existing['expected_status']),
        timeout=data.get('timeout', existing['timeout']),
        interval=data.get('check_interval', existing['check_interval']),
        enabled=data.get('enabled', bool(existing['enabled'])),
        retries=data.get('retries', existing.get('retries', 3)),
        flap_window=data.get('flap_window', existing.get('flap_window', 3600)),
        flap_threshold=data.get('flap_threshold', existing.get('flap_threshold', 5)),
        suppression_duration=data.get('suppression_duration', existing.get('suppression_duration', 3600))
    )
    
    db.add_service(service)
    
    old_name = existing['service_name']
    if old_name in monitor.monitoring_tasks:
        monitor.monitoring_tasks[old_name].cancel()
        del monitor.monitoring_tasks[old_name]
    
    if service.enabled:
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({'success': True})

async def delete_service(request: web.Request):
    """Delete a service"""
    service_id = int(request.match_info['service_id'])
    
    service = db.get_service(service_id)
    if not service:
        return _json({'error': 'Service not found'}, status=404)
    
    service_name = service['service_name']
    
    if service_name in monitor.monitoring_tasks:
        monitor.monitoring_tasks[service_name].cancel()
        del monitor.monitoring_tasks[service_name]
    
    db.delete_service(service_id)
    
    return _json({'success': True})

async def get_uptime(request: web.Request):
    """Get uptime stats for a service"""
    service_name = request.match_info['service_name']
    
    try:
        hours = int(request.rel_url.query.get('hours', 24))
    except:
        hours = 24
    
    metrics = db.get_metrics(service_name, hours)
    
    if not metrics:
        return _json({
            'service_name': service_name,
            'uptime_percentage': 100,
            'total_checks': 0,
            'successful_checks': 0,
            'failed_checks': 0,
            'avg_response_time': 0
        })
    
    total = len(metrics)
    successful = sum(1 for m in metrics if m.status == 'up')
    uptime_pct = round((successful / total) * 100, 1) if total > 0 else 100
    
    response_times = [m.response_time for m in metrics if m.response_time]
    avg_response = round(sum(response_times) / len(response_times), 3) if response_times else 0
    
    return _json({
        'service_name': service_name,
        'uptime_percentage': uptime_pct,
        'total_checks': total,
        'successful_checks': successful,
        'failed_checks': total - successful,
        'avg_response_time': avg_response
    })

async def get_incidents(request: web.Request):
    """Get recent incidents"""
    try:
        days = int(request.rel_url.query.get('days', 7))
    except:
        days = 7
    
    hours = days * 24
    incidents_data = db.get_incidents(hours=hours)
    
    return _json(incidents_data)

async def reset_health(request: web.Request):
    """Reset all health data"""
    try:
        deleted_metrics = db.purge_old_metrics(days=0)
        return _json({'success': True, 'deleted_metrics': deleted_metrics})
    except Exception as e:
        return _json({'error': str(e)}, status=500)

async def reset_incidents(request: web.Request):
    """Clear all incidents"""
    try:
        deleted_incidents = db.purge_old_incidents(days=0)
        return _json({'success': True, 'deleted': deleted_incidents})
    except Exception as e:
        return _json({'error': str(e)}, status=500)

async def reset_service_data(request: web.Request):
    """Reset data for a specific service"""
    service_name = request.match_info['service_name']
    
    try:
        deleted_metrics = db.reset_service_metrics(service_name)
        deleted_incidents = db.reset_service_incidents(service_name)
        
        return _json({
            'success': True,
            'deleted_metrics': deleted_metrics,
            'deleted_incidents': deleted_incidents
        })
    except Exception as e:
        return _json({'error': str(e)}, status=500)

async def purge_all(request: web.Request):
    """Purge all metrics, incidents, and speed tests"""
    try:
        deleted_metrics = db.purge_old_metrics(days=0)
        deleted_incidents = db.purge_old_incidents(days=0)
        deleted_speedtests = db.purge_speed_tests(days=0)
        return _json({
            'success': True,
            'deleted_metrics': deleted_metrics,
            'deleted_incidents': deleted_incidents,
            'deleted_speedtests': deleted_speedtests,
            'total_deleted': deleted_metrics + deleted_incidents + deleted_speedtests
        })
    except Exception as e:
        return _json({'error': str(e)}, status=500)

async def purge_week(request: web.Request):
    """Purge metrics, incidents, and speed tests older than 1 week"""
    try:
        deleted_metrics = db.purge_old_metrics(days=7)
        deleted_incidents = db.purge_old_incidents(days=7)
        deleted_speedtests = db.purge_speed_tests(days=7)
        return _json({
            'success': True,
            'deleted_metrics': deleted_metrics,
            'deleted_incidents': deleted_incidents,
            'deleted_speedtests': deleted_speedtests,
            'total_deleted': deleted_metrics + deleted_incidents + deleted_speedtests
        })
    except Exception as e:
        return _json({'error': str(e)}, status=500)

async def purge_month(request: web.Request):
    """Purge metrics, incidents, and speed tests older than 1 month"""
    try:
        deleted_metrics = db.purge_old_metrics(days=30)
        deleted_incidents = db.purge_old_incidents(days=30)
        deleted_speedtests = db.purge_speed_tests(days=30)
        return _json({
            'success': True,
            'deleted_metrics': deleted_metrics,
            'deleted_incidents': deleted_incidents,
            'deleted_speedtests': deleted_speedtests,
            'total_deleted': deleted_metrics + deleted_incidents + deleted_speedtests
        })
    except Exception as e:
        return _json({'error': str(e)}, status=500)


# ============================================================================
# API ROUTES - NETWORK MONITORING
# ============================================================================

async def network_scan(request: web.Request):
    """Trigger a network scan"""
    devices = await scanner.scan_network()
    
    for device in devices:
        db.add_or_update_device(device)
    
    new_devices = sum(1 for d in devices if not db.get_device(d.mac_address))
    
    return _json({
        'success': True,
        'devices_found': len(devices),
        'new_devices': new_devices
    })

async def network_devices_list(request: web.Request):
    """List all network devices"""
    devices = db.get_all_devices()
    return _json({'devices': devices})

async def network_device_get(request: web.Request):
    """Get a specific device"""
    mac_address = request.match_info['mac_address']
    device = db.get_device(mac_address)
    
    if not device:
        return _json({'error': 'Device not found'}, status=404)
    
    return _json({'device': device})

async def network_device_update(request: web.Request):
    """Update device settings"""
    mac_address = request.match_info['mac_address']
    
    try:
        data = await request.json()
    except:
        return _json({'error': 'Invalid JSON'}, status=400)
    
    device = db.get_device(mac_address)
    if not device:
        return _json({'error': 'Device not found'}, status=404)
    
    db.update_device_settings(
        mac_address,
        is_permanent=data.get('is_permanent'),
        is_monitored=data.get('is_monitored'),
        custom_name=data.get('custom_name')
    )
    
    return _json({'success': True})

async def network_device_delete(request: web.Request):
    """Delete a device"""
    mac_address = request.match_info['mac_address']
    db.delete_device(mac_address)
    return _json({'success': True})

async def network_stats(request: web.Request):
    """Get network monitoring statistics"""
    stats = db.get_network_stats()
    return _json(stats)

async def network_events_list(request: web.Request):
    """List recent network events"""
    try:
        hours = int(request.rel_url.query.get('hours', 24))
    except:
        hours = 24
    
    events = db.get_recent_network_events(hours)
    return _json({'events': events})

async def network_monitoring_start(request: web.Request):
    """Start network monitoring"""
    await scanner.start_monitoring()
    return _json({'success': True, 'monitoring': True})

async def network_monitoring_stop(request: web.Request):
    """Stop network monitoring"""
    await scanner.stop_monitoring()
    return _json({'success': True, 'monitoring': False})

async def network_monitoring_status(request: web.Request):
    """Get network monitoring status"""
    return _json({
        'monitoring': scanner.monitoring,
        'alert_new_devices': scanner.alert_new_devices
    })

async def network_settings_update(request: web.Request):
    """Update network monitoring settings"""
    try:
        data = await request.json()
    except:
        return _json({'error': 'Invalid JSON'}, status=400)
    
    if 'alert_new_devices' in data:
        scanner.alert_new_devices = bool(data['alert_new_devices'])
    
    return _json({'success': True})


# ============================================================================
# API ROUTES - SPEED TEST
# ============================================================================

async def speedtest_run(request: web.Request):
    """Trigger a manual speed test"""
    if speed_monitor.testing:
        return _json({"error": "Speed test already in progress"}, status=429)
    
    result = await speed_monitor.run_speedtest()
    
    if result:
        return _json({
            'success': True,
            'result': {
                'download': result.download,
                'upload': result.upload,
                'ping': result.ping,
                'server': result.server,
                'jitter': result.jitter,
                'packet_loss': result.packet_loss,
                'timestamp': result.timestamp
            }
        })
    else:
        return _json({"error": "Speed test failed"}, status=500)

async def speedtest_history(request: web.Request):
    """Get speed test history"""
    try:
        hours = int(request.rel_url.query.get('hours', 168))
    except:
        hours = 168
    
    history = db.get_speed_test_history(hours)
    return _json({'tests': history})

async def speedtest_latest(request: web.Request):
    """Get latest speed test"""
    latest = db.get_latest_speed_test()
    if latest:
        return _json({'test': latest})
    else:
        return _json({"error": "No tests found"}, status=404)

async def speedtest_stats(request: web.Request):
    """Get speed test statistics"""
    stats = db.get_speed_test_stats()
    averages = db.get_speed_test_averages(last_n=5)
    
    return _json({
        **stats,
        'recent_avg_download': averages['avg_download'],
        'recent_avg_upload': averages['avg_upload'],
        'recent_avg_ping': averages['avg_ping']
    })

async def speedtest_start_monitoring(request: web.Request):
    """Start automatic monitoring with settings"""
    try:
        data = await request.json()
    except:
        data = {}
    
    settings = {
        'schedule_mode': data.get('schedule_mode', 'interval'),
        'interval_hours': data.get('interval_hours', 12),
        'schedule_times': data.get('schedule_times', []),
        'degrade_threshold': data.get('degrade_threshold', 0.7),
        'ping_threshold': data.get('ping_threshold', 1.5)
    }
    
    await speed_monitor.start_monitoring(settings)
    
    return _json({
        'success': True,
        'monitoring': True,
        'settings': settings
    })

async def speedtest_stop_monitoring(request: web.Request):
    """Stop automatic monitoring"""
    await speed_monitor.stop_monitoring()
    return _json({'success': True, 'monitoring': False})

async def speedtest_monitoring_status(request: web.Request):
    """Get monitoring status"""
    return _json({
        'monitoring': speed_monitor.monitoring,
        'testing': speed_monitor.testing,
        'schedule_mode': speed_monitor.schedule_mode,
        'interval_hours': speed_monitor.interval_hours,
        'schedule_times': speed_monitor.schedule_times,
        'consecutive_failures': speed_monitor.consecutive_failures
    })

async def speedtest_update_settings(request: web.Request):
    """Update settings"""
    try:
        data = await request.json()
    except:
        return _json({"error": "bad json"}, status=400)
    
    if 'interval_hours' in data:
        interval = int(data['interval_hours'])
        if 1 <= interval <= 24:
            speed_monitor.interval_hours = interval
    
    if 'degrade_threshold' in data:
        threshold = float(data['degrade_threshold'])
        if 0.1 <= threshold <= 1.0:
            speed_monitor.degrade_threshold = threshold
    
    if 'ping_threshold' in data:
        threshold = float(data['ping_threshold'])
        if 1.0 <= threshold <= 3.0:
            speed_monitor.ping_threshold = threshold
    
    return _json({'success': True})

async def speedtest_get_settings(request: web.Request):
    """Get current speed test settings"""
    settings = db.get_speed_test_settings()
    return _json(settings)

async def speedtest_update_schedule(request: web.Request):
    """Update schedule settings (mode, interval, or times)"""
    try:
        data = await request.json()
    except:
        return _json({"error": "Invalid JSON"}, status=400)
    
    settings = db.get_speed_test_settings()
    
    # Update settings
    if 'schedule_mode' in data:
        if data['schedule_mode'] in ['interval', 'scheduled']:
            settings['schedule_mode'] = data['schedule_mode']
    
    if 'interval_hours' in data:
        interval = int(data['interval_hours'])
        if 1 <= interval <= 24:
            settings['interval_hours'] = interval
    
    if 'schedule_times' in data:
        # Validate times format (HH:MM)
        times = data['schedule_times']
        if isinstance(times, list):
            settings['schedule_times'] = times
    
    if 'degrade_threshold' in data:
        threshold = float(data['degrade_threshold'])
        if 0.1 <= threshold <= 1.0:
            settings['degrade_threshold'] = threshold
    
    if 'ping_threshold' in data:
        threshold = float(data['ping_threshold'])
        if 1.0 <= threshold <= 3.0:
            settings['ping_threshold'] = threshold
    
    # Save to database
    db.update_speed_test_settings(settings)
    
    # Update monitor if it's running
    if speed_monitor.monitoring:
        speed_monitor.schedule_mode = settings['schedule_mode']
        speed_monitor.interval_hours = settings['interval_hours']
        speed_monitor.schedule_times = settings['schedule_times']
        speed_monitor.degrade_threshold = settings['degrade_threshold']
        speed_monitor.ping_threshold = settings['ping_threshold']
    
    return _json({'success': True, 'settings': settings})



# ============================================================================
# MODULE INITIALIZATION
# ============================================================================

def register_routes(app: web.Application):
    """Register all analytics API routes"""
    # Service management
    app.router.add_get('/api/analytics/health-score', get_health_score)
    app.router.add_get('/api/analytics/services', list_services)
    app.router.add_get('/api/analytics/services/{service_id}', get_service)
    app.router.add_post('/api/analytics/services', add_service)
    app.router.add_put('/api/analytics/services/{service_id}', update_service)
    app.router.add_delete('/api/analytics/services/{service_id}', delete_service)
    app.router.add_get('/api/analytics/uptime/{service_name}', get_uptime)
    app.router.add_get('/api/analytics/incidents', get_incidents)
    
    # Data management
    app.router.add_post('/api/analytics/reset-health', reset_health)
    app.router.add_post('/api/analytics/reset-incidents', reset_incidents)
    app.router.add_post('/api/analytics/reset-service/{service_name}', reset_service_data)
    app.router.add_post('/api/analytics/purge-all', purge_all)
    app.router.add_post('/api/analytics/purge-week', purge_week)
    app.router.add_post('/api/analytics/purge-month', purge_month)
    
    # Network monitoring
    app.router.add_post('/api/analytics/network/scan', network_scan)
    app.router.add_get('/api/analytics/network/devices', network_devices_list)
    app.router.add_get('/api/analytics/network/devices/{mac_address}', network_device_get)
    app.router.add_put('/api/analytics/network/devices/{mac_address}', network_device_update)
    app.router.add_delete('/api/analytics/network/devices/{mac_address}', network_device_delete)
    app.router.add_get('/api/analytics/network/stats', network_stats)
    app.router.add_get('/api/analytics/network/events', network_events_list)
    app.router.add_post('/api/analytics/network/monitoring/start', network_monitoring_start)
    app.router.add_post('/api/analytics/network/monitoring/stop', network_monitoring_stop)
    app.router.add_get('/api/analytics/network/monitoring/status', network_monitoring_status)
    app.router.add_put('/api/analytics/network/settings', network_settings_update)
    
    # Speed test routes
    app.router.add_post('/api/analytics/speedtest/run', speedtest_run)
    app.router.add_get('/api/analytics/speedtest/history', speedtest_history)
    app.router.add_get('/api/analytics/speedtest/latest', speedtest_latest)
    app.router.add_get('/api/analytics/speedtest/stats', speedtest_stats)
    app.router.add_post('/api/analytics/speedtest/monitoring/start', speedtest_start_monitoring)
    app.router.add_post('/api/analytics/speedtest/monitoring/stop', speedtest_stop_monitoring)
    app.router.add_get('/api/analytics/speedtest/monitoring/status', speedtest_monitoring_status)
    app.router.add_put('/api/analytics/speedtest/settings', speedtest_update_settings)
    app.router.add_get('/api/analytics/speedtest/schedule', speedtest_get_settings)
    app.router.add_post('/api/analytics/speedtest/schedule', speedtest_update_schedule)

async def init_analytics(app: web.Application, notification_callback: Optional[Callable] = None):
    """Initialize analytics module"""
    global db, monitor, scanner, speed_monitor
    
    db = AnalyticsDB()
    
    callback = notification_callback or analytics_notify
    
    monitor = HealthMonitor(db, callback)
    scanner = NetworkScanner(db)
    scanner.set_notification_callback(callback)
    speed_monitor = SpeedTestMonitor(db)
    speed_monitor.set_notification_callback(callback)
    
    await monitor.start_all()
    
    register_routes(app)
    
    logger.info("Analytics module initialized with speed test monitoring")

async def shutdown_analytics():
    """Shutdown analytics module"""
    if monitor:
        await monitor.stop_all()
    if scanner:
        await scanner.stop_monitoring()
    if speed_monitor:
        await speed_monitor.stop_monitoring()
