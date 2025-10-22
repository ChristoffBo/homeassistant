"""
Jarvis Prime - Analytics & Uptime Monitoring Module
aiohttp-compatible version for Jarvis Prime

ðŸ”¥ðŸ”¥ðŸ”¥ VERSION: 2025-01-19-FINAL-FIX ðŸ”¥ðŸ”¥ðŸ”¥

FIXED: sqlite3.Row access
FIXED: notification callback checks  
FIXED: arp-scan garbage filtering
FIXED: dashboard stats
FIXED: purge functions
ADDED: comprehensive logging

If you see "VERSION: 2025-01-19-FINAL-FIX" in your logs, you have the fixed version.
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

# Print version on import
logger.info("ðŸ”¥ Analytics Module VERSION: 2025-01-19-FINAL-FIX ðŸ”¥")



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
    9117: {'name': 'rTorrent/ruTorrent', 'category': 'download', 'path': '/'},
    
    # Media Servers
    32400: {'name': 'Plex', 'category': 'media-server', 'path': '/identity'},
    8096: {'name': 'Jellyfin', 'category': 'media-server', 'path': '/System/Info/Public'},
    8920: {'name': 'Emby', 'category': 'media-server', 'path': '/System/Info/Public'},
    8324: {'name': 'Plex for Roku', 'category': 'media-server', 'path': '/'},
    7359: {'name': 'Plex DLNA', 'category': 'media-server', 'path': None},
    1900: {'name': 'Plex DLNA', 'category': 'media-server', 'path': None},
    8200: {'name': 'Tautulli', 'category': 'media-server', 'path': '/api/v2'},
    
    # Home Automation
    8123: {'name': 'Home Assistant', 'category': 'automation', 'path': '/api/'},
    1880: {'name': 'Node-RED', 'category': 'automation', 'path': '/'},
    8088: {'name': 'Domoticz', 'category': 'automation', 'path': '/json.htm'},
    8090: {'name': 'OpenHAB', 'category': 'automation', 'path': '/rest/'},
    8091: {'name': 'Homebridge', 'category': 'automation', 'path': '/'},
    51826: {'name': 'Homebridge', 'category': 'automation', 'path': None},
    8581: {'name': 'Home Assistant Node-RED', 'category': 'automation', 'path': '/'},
    1883: {'name': 'MQTT Broker', 'category': 'automation', 'path': None},
    8883: {'name': 'MQTT Broker (SSL)', 'category': 'automation', 'path': None},
    9883: {'name': 'MQTT Broker (WebSocket)', 'category': 'automation', 'path': None},
    8125: {'name': 'Zigbee2MQTT', 'category': 'automation', 'path': '/api/info'},
    
    # Monitoring & Management
    3001: {'name': 'Uptime Kuma', 'category': 'monitoring', 'path': '/api/status-page'},
    9000: {'name': 'Portainer', 'category': 'management', 'path': '/api/status'},
    19999: {'name': 'Netdata', 'category': 'monitoring', 'path': '/api/v1/info'},
    3000: {'name': 'Grafana', 'category': 'monitoring', 'path': '/api/health'},
    9090: {'name': 'Prometheus', 'category': 'monitoring', 'path': '/-/healthy'},
    8086: {'name': 'InfluxDB', 'category': 'monitoring', 'path': '/ping'},
    9093: {'name': 'Alertmanager', 'category': 'monitoring', 'path': '/api/v1/status'},
    9100: {'name': 'Node Exporter', 'category': 'monitoring', 'path': '/metrics'},
    9115: {'name': 'Blackbox Exporter', 'category': 'monitoring', 'path': '/metrics'},
    9182: {'name': 'Cloudflare Exporter', 'category': 'monitoring', 'path': '/metrics'},
    8082: {'name': 'Chronograf', 'category': 'monitoring', 'path': '/'},
    8888: {'name': 'Cockpit', 'category': 'monitoring', 'path': '/'},
    10000: {'name': 'Webmin', 'category': 'management', 'path': '/'},
    9090: {'name': 'Cockpit', 'category': 'management', 'path': '/'},
    
    # Network Services & DNS
    53: {'name': 'DNS Server', 'category': 'network', 'path': None},
    80: {'name': 'HTTP Server', 'category': 'network', 'path': '/'},
    443: {'name': 'HTTPS Server', 'category': 'network', 'path': '/'},
    5335: {'name': 'Pi-hole', 'category': 'network', 'path': '/admin/api.php'},
    8888: {'name': 'Technitium DNS', 'category': 'network', 'path': '/api/user/session/get'},
    853: {'name': 'DNS-over-TLS', 'category': 'network', 'path': None},
    5300: {'name': 'AdGuard Home', 'category': 'network', 'path': '/control/status'},
    3000: {'name': 'AdGuard Home', 'category': 'network', 'path': '/control/status'},
    
    # VPN & Proxy
    8888: {'name': 'Gluetun', 'category': 'vpn', 'path': '/v1/publicip/ip'},
    1080: {'name': 'Shadowsocks', 'category': 'vpn', 'path': None},
    8388: {'name': 'Shadowsocks', 'category': 'vpn', 'path': None},
    1194: {'name': 'OpenVPN', 'category': 'vpn', 'path': None},
    51820: {'name': 'WireGuard', 'category': 'vpn', 'path': None},
    8118: {'name': 'Privoxy', 'category': 'proxy', 'path': '/'},
    3128: {'name': 'Squid Proxy', 'category': 'proxy', 'path': '/'},
    8443: {'name': 'Nginx Proxy Manager', 'category': 'proxy', 'path': '/api/'},
    81: {'name': 'Nginx Proxy Manager', 'category': 'proxy', 'path': '/api/'},
    8090: {'name': 'Traefik', 'category': 'proxy', 'path': '/api/overview'},
    8080: {'name': 'Traefik', 'category': 'proxy', 'path': '/dashboard/'},
    2019: {'name': 'Caddy', 'category': 'proxy', 'path': '/config/'},
    
    # Storage & Backup
    5000: {'name': 'Synology DSM', 'category': 'storage', 'path': '/'},
    5001: {'name': 'Synology DSM (HTTPS)', 'category': 'storage', 'path': '/'},
    9001: {'name': 'MinIO Console', 'category': 'storage', 'path': '/'},
    9000: {'name': 'MinIO API', 'category': 'storage', 'path': '/minio/health/live'},
    8200: {'name': 'Duplicati', 'category': 'backup', 'path': '/api/v1/serverstate'},
    8083: {'name': 'Restic', 'category': 'backup', 'path': '/'},
    9090: {'name': 'Kopia', 'category': 'backup', 'path': '/api/v1/repo/status'},
    5076: {'name': 'Syncthing', 'category': 'storage', 'path': '/rest/system/version'},
    8384: {'name': 'Syncthing', 'category': 'storage', 'path': '/rest/system/version'},
    873: {'name': 'Rsync', 'category': 'backup', 'path': None},
    445: {'name': 'SMB/CIFS', 'category': 'storage', 'path': None},
    139: {'name': 'NetBIOS', 'category': 'storage', 'path': None},
    2049: {'name': 'NFS', 'category': 'storage', 'path': None},
    
    # Databases
    3306: {'name': 'MySQL/MariaDB', 'category': 'database', 'path': None},
    5432: {'name': 'PostgreSQL', 'category': 'database', 'path': None},
    6379: {'name': 'Redis', 'category': 'database', 'path': None},
    27017: {'name': 'MongoDB', 'category': 'database', 'path': None},
    8529: {'name': 'ArangoDB', 'category': 'database', 'path': '/_api/version'},
    7474: {'name': 'Neo4j', 'category': 'database', 'path': '/'},
    9042: {'name': 'Cassandra', 'category': 'database', 'path': None},
    5984: {'name': 'CouchDB', 'category': 'database', 'path': '/'},
    8091: {'name': 'Couchbase', 'category': 'database', 'path': '/pools'},
    
    # Communication & Messaging
    8065: {'name': 'Mattermost', 'category': 'communication', 'path': '/api/v4/system/ping'},
    3478: {'name': 'Gotify', 'category': 'communication', 'path': '/health'},
    5000: {'name': 'Rocket.Chat', 'category': 'communication', 'path': '/api/info'},
    9000: {'name': 'Matrix Synapse', 'category': 'communication', 'path': '/_matrix/client/versions'},
    8008: {'name': 'Matrix Synapse', 'category': 'communication', 'path': '/_matrix/client/versions'},
    5222: {'name': 'Prosody XMPP', 'category': 'communication', 'path': None},
    5223: {'name': 'Prosody XMPP (SSL)', 'category': 'communication', 'path': None},
    1025: {'name': 'MailHog', 'category': 'communication', 'path': '/api/v1/messages'},
    8025: {'name': 'MailHog', 'category': 'communication', 'path': '/api/v1/messages'},
    
    # Security & Authentication
    8200: {'name': 'Vault', 'category': 'security', 'path': '/v1/sys/health'},
    3012: {'name': 'Vaultwarden', 'category': 'security', 'path': '/api/'},
    8000: {'name': 'Authelia', 'category': 'security', 'path': '/api/health'},
    9091: {'name': 'Authentik', 'category': 'security', 'path': '/api/v3/'},
    8080: {'name': 'Keycloak', 'category': 'security', 'path': '/health'},
    9000: {'name': 'Keycloak', 'category': 'security', 'path': '/health'},
    8899: {'name': 'Fail2ban Exporter', 'category': 'security', 'path': '/metrics'},
    
    # Development & CI/CD
    8080: {'name': 'Jenkins', 'category': 'development', 'path': '/login'},
    9200: {'name': 'Elasticsearch', 'category': 'development', 'path': '/'},
    5601: {'name': 'Kibana', 'category': 'development', 'path': '/api/status'},
    9000: {'name': 'SonarQube', 'category': 'development', 'path': '/api/system/status'},
    3000: {'name': 'Gitea', 'category': 'development', 'path': '/api/v1/version'},
    3001: {'name': 'Gogs', 'category': 'development', 'path': '/api/v1/version'},
    8080: {'name': 'GitLab', 'category': 'development', 'path': '/-/health'},
    8929: {'name': 'GitLab', 'category': 'development', 'path': '/-/health'},
    8083: {'name': 'VS Code Server', 'category': 'development', 'path': '/healthz'},
    8443: {'name': 'Code Server', 'category': 'development', 'path': '/healthz'},
    8384: {'name': 'Drone CI', 'category': 'development', 'path': '/healthz'},
    9999: {'name': 'Argo CD', 'category': 'development', 'path': '/healthz'},
    8080: {'name': 'Nexus', 'category': 'development', 'path': '/service/rest/v1/status'},
    8081: {'name': 'Nexus', 'category': 'development', 'path': '/service/rest/v1/status'},
    
    # Container & Orchestration
    2375: {'name': 'Docker API', 'category': 'container', 'path': None},
    2376: {'name': 'Docker API (TLS)', 'category': 'container', 'path': None},
    6443: {'name': 'Kubernetes API', 'category': 'container', 'path': '/healthz'},
    10250: {'name': 'Kubelet', 'category': 'container', 'path': '/healthz'},
    8001: {'name': 'Kubernetes Dashboard', 'category': 'container', 'path': '/'},
    9090: {'name': 'Rancher', 'category': 'container', 'path': '/healthz'},
    
    # Game Servers
    25565: {'name': 'Minecraft', 'category': 'gaming', 'path': None},
    25575: {'name': 'Minecraft RCON', 'category': 'gaming', 'path': None},
    27015: {'name': 'Steam/Source Server', 'category': 'gaming', 'path': None},
    7777: {'name': 'Terraria', 'category': 'gaming', 'path': None},
    7778: {'name': 'Satisfactory', 'category': 'gaming', 'path': None},
    27016: {'name': 'Rust', 'category': 'gaming', 'path': None},
    2456: {'name': 'Valheim', 'category': 'gaming', 'path': None},
    19132: {'name': 'Minecraft Bedrock', 'category': 'gaming', 'path': None},
    
    # Smart Home & IoT
    8086: {'name': 'ESPHome', 'category': 'iot', 'path': '/'},
    6052: {'name': 'ESPHome', 'category': 'iot', 'path': '/'},
    8080: {'name': 'Tasmota', 'category': 'iot', 'path': '/cm?cmnd=Status'},
    8266: {'name': 'ESP8266', 'category': 'iot', 'path': '/'},
    8888: {'name': 'Shelly', 'category': 'iot', 'path': '/status'},
    8123: {'name': 'Octoprint', 'category': 'iot', 'path': '/api/version'},
    5000: {'name': 'Octoprint', 'category': 'iot', 'path': '/api/version'},
    
    # Photos & Media Management
    2342: {'name': 'PhotoPrism', 'category': 'photos', 'path': '/api/v1/status'},
    2283: {'name': 'Immich', 'category': 'photos', 'path': '/api/server-info/ping'},
    8080: {'name': 'Photoview', 'category': 'photos', 'path': '/api/graphql'},
    8787: {'name': 'Kavita', 'category': 'photos', 'path': '/api/health'},
    8080: {'name': 'Komga', 'category': 'photos', 'path': '/api/v1/actuator/health'},
    
    # Miscellaneous
    8096: {'name': 'Firefly III', 'category': 'finance', 'path': '/api/v1/about'},
    5252: {'name': 'OctoPrint', 'category': 'misc', 'path': '/api/version'},
    7575: {'name': 'Speedtest Tracker', 'category': 'misc', 'path': '/api/healthcheck'},
    8080: {'name': 'Home Assistant Supervisor', 'category': 'misc', 'path': '/supervisor/info'},
    8112: {'name': 'FileBrowser', 'category': 'misc', 'path': '/api/health'},
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
            # Convert Row to dict for safe access
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
            # Store the ID for reference
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
        
        # Calculate uptime percentage and format response time for each service
        for service in services:
            # Uptime percentage
            if service['total_checks_24h'] and service['total_checks_24h'] > 0:
                service['uptime_24h'] = round((service['successful_checks_24h'] / service['total_checks_24h']) * 100, 1)
            else:
                service['uptime_24h'] = 100.0 if service.get('current_status') == 'up' else 0.0
            
            # Response time - use average if available, otherwise use latest
            if service['avg_response_24h'] is not None:
                service['avg_response'] = round(service['avg_response_24h'] * 1000, 1)  # Convert to ms
            elif service['latest_response_time'] is not None:
                service['avg_response'] = round(service['latest_response_time'] * 1000, 1)  # Convert to ms
            else:
                service['avg_response'] = None
            
            # Clean up temporary fields
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
        
        # Find the most recent unresolved incident
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
        """Get recent incidents - PATCHED to return consistent format"""
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
        
        # Check if device exists
        cur.execute("SELECT first_seen FROM network_devices WHERE mac_address = ?", (device.mac_address,))
        row = cur.fetchone()
        
        if row:
            # Update existing device
            cur.execute("""
                UPDATE network_devices 
                SET ip_address = ?, hostname = ?, vendor = ?, last_seen = ?, updated_at = ?
                WHERE mac_address = ?
            """, (device.ip_address, device.hostname, device.vendor, now, now, device.mac_address))
        else:
            # Insert new device
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
        
        # Devices seen in last 24 hours
        cutoff = int(time.time()) - 86400
        cur.execute("SELECT COUNT(*) FROM network_devices WHERE last_seen > ?", (cutoff,))
        active_24h = cur.fetchone()[0]
        
        # Last scan time
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
        
        # Check if endpoint contains this IP
        cur.execute("""
            SELECT COUNT(*) as count
            FROM analytics_services
            WHERE endpoint LIKE ?
        """, (f'%{ip_address}%',))
        
        result = cur.fetchone()
        conn.close()
        
        return result[0] > 0


class HealthMonitor:
    """Service health monitoring with retry and flap protection"""
    
    def __init__(self, db: AnalyticsDB, notification_callback: Callable):
        self.db = db
        self.notify = notification_callback
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.flap_trackers: Dict[str, FlapTracker] = {}
    
    async def check_service(self, service: HealthCheck) -> ServiceMetric:
        """Perform a single health check with retry logic"""
        start_time = time.time()
        
        for attempt in range(service.retries):
            try:
                if service.check_type == 'http':
                    async with aiohttp.ClientSession() as session:
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
                                error_msg = f"Status {response.status} (expected {service.expected_status})"
                                if attempt < service.retries - 1:
                                    await asyncio.sleep(1)
                                    continue
                                return ServiceMetric(
                                    service_name=service.service_name,
                                    timestamp=int(time.time()),
                                    status='down',
                                    response_time=response_time,
                                    error_message=error_msg
                                )
                
                elif service.check_type == 'tcp':
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(service.endpoint.split(':')[0], int(service.endpoint.split(':')[1])),
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
                        if attempt < service.retries - 1:
                            await asyncio.sleep(1)
                            continue
                        response_time = time.time() - start_time
                        return ServiceMetric(
                            service_name=service.service_name,
                            timestamp=int(time.time()),
                            status='down',
                            response_time=response_time,
                            error_message=str(e)
                        )
                
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
                            if attempt < service.retries - 1:
                                await asyncio.sleep(1)
                                continue
                            return ServiceMetric(
                                service_name=service.service_name,
                                timestamp=int(time.time()),
                                status='down',
                                response_time=response_time,
                                error_message='Ping failed'
                            )
                    except Exception as e:
                        if attempt < service.retries - 1:
                            await asyncio.sleep(1)
                            continue
                        response_time = time.time() - start_time
                        return ServiceMetric(
                            service_name=service.service_name,
                            timestamp=int(time.time()),
                            status='down',
                            response_time=response_time,
                            error_message=str(e)
                        )
            
            except Exception as e:
                if attempt < service.retries - 1:
                    await asyncio.sleep(1)
                    continue
                response_time = time.time() - start_time
                return ServiceMetric(
                    service_name=service.service_name,
                    timestamp=int(time.time()),
                    status='down',
                    response_time=response_time,
                    error_message=str(e)
                )
        
        # Should never reach here, but just in case
        return ServiceMetric(
            service_name=service.service_name,
            timestamp=int(time.time()),
            status='down',
            response_time=time.time() - start_time,
            error_message='All retries failed'
        )
    
    def should_suppress_notification(self, service_name: str, status: str) -> bool:
        """Check if notification should be suppressed due to flapping"""
        if service_name not in self.flap_trackers:
            self.flap_trackers[service_name] = FlapTracker()
        
        tracker = self.flap_trackers[service_name]
        now = time.time()
        
        # Check if currently suppressed
        if tracker.suppressed_until and now < tracker.suppressed_until:
            return True
        
        # If status hasn't changed, not a flap
        if tracker.last_status == status:
            return False
        
        # Record this state change
        tracker.flap_times.append(now)
        tracker.last_status = status
        
        # Clean old flap times outside window
        service = None
        for s in self.db.get_services():
            if s.service_name == service_name:
                service = s
                break
        
        if not service:
            return False
        
        # Remove flaps outside the window
        while tracker.flap_times and now - tracker.flap_times[0] > service.flap_window:
            tracker.flap_times.popleft()
        
        # Check if flapping threshold exceeded
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
                
                # Get previous status
                recent_metrics = self.db.get_metrics(service.service_name, hours=1)
                previous_status = recent_metrics[1].status if len(recent_metrics) > 1 else None
                
                # Handle status changes
                if metric.status == 'down' and previous_status != 'down':
                    # Service went down
                    self.db.create_incident(service.service_name, metric.error_message)
                    
                    if not self.should_suppress_notification(service.service_name, 'down'):
                        await analytics_notify(
                            service.service_name,
                            'down',
                            f"Service is DOWN: {metric.error_message or 'No response'}"
                        )
                
                elif metric.status == 'up' and previous_status == 'down':
                    # Service recovered
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


class NetworkScanner:
    """Network device scanner and monitor"""
    
    def __init__(self, db: AnalyticsDB):
        self.db = db
        self.monitoring = False
        self.scanning = False
        self.monitor_interval = 300  # 5 minutes default
        self.alert_new_devices = True
        self.notification_callback = None
        self._monitor_task = None
    
    def set_notification_callback(self, callback: Callable):
        """Set the notification callback"""
        self.notification_callback = callback
    
    def set_alert_new_devices(self, enabled: bool):
        """Enable/disable alerts for new devices"""
        self.alert_new_devices = enabled
    
    async def detect_services(self, ip_address: str) -> List[Dict]:
        """Probe device for known services by scanning common ports"""
        detected_services = []
        
        # Scan common ports for services
        for port, service_info in SERVICE_FINGERPRINTS.items():
            try:
                # Try to connect to the port with short timeout
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip_address, port),
                    timeout=2
                )
                writer.close()
                await writer.wait_closed()
                
                # Port is open, verify service if HTTP path available
                service_name = service_info['name']
                verified = False
                
                if service_info['path']:
                    try:
                        # Try HTTP request to verify service
                        async with aiohttp.ClientSession() as session:
                            url = f"http://{ip_address}:{port}{service_info['path']}"
                            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                                if response.status < 500:  # Any non-server-error means service is there
                                    verified = True
                    except:
                        # If HTTP fails but port is open, still count it
                        verified = True
                else:
                    # No HTTP check needed, port being open is enough
                    verified = True
                
                if verified:
                    detected_services.append({
                        'name': service_name,
                        'port': port,
                        'category': service_info['category'],
                        'endpoint': f"{ip_address}:{port}"
                    })
                    logger.info(f"Detected {service_name} on {ip_address}:{port}")
                
            except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                # Port closed or service not responding
                pass
            except Exception as e:
                # Unexpected error, log but continue
                logger.debug(f"Error probing {ip_address}:{port}: {e}")
        
        return detected_services
    
    async def scan_network(self) -> List[NetworkDevice]:
        """Scan network for devices using ARP"""
        self.scanning = True
        devices = []
        
        try:
            # Use arp-scan if available, otherwise fall back to arp -a
            try:
                proc = await asyncio.create_subprocess_exec(
                    'arp-scan', '-l', '-q',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                
                if proc.returncode == 0:
                    for line in stdout.decode().splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            ip_address = parts[0]
                            mac_address = parts[1].upper()
                            
                            # Validate IP address format
                            if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                                continue
                            
                            # Validate MAC address format
                            if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', mac_address):
                                continue
                            
                            # Try to get hostname
                            hostname = None
                            try:
                                hostname = socket.gethostbyaddr(ip_address)[0]
                            except:
                                pass
                            
                            devices.append(NetworkDevice(
                                mac_address=mac_address,
                                ip_address=ip_address,
                                hostname=hostname,
                                first_seen=int(time.time()),
                                last_seen=int(time.time())
                            ))
            
            except FileNotFoundError:
                # Fall back to arp -a
                proc = await asyncio.create_subprocess_exec(
                    'arp', '-a',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                
                for line in stdout.decode().splitlines():
                    # Parse arp -a output
                    match = re.search(r'\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]+)', line)
                    if match:
                        ip_address = match.group(1)
                        mac_address = match.group(2).upper()
                        
                        # Try to get hostname
                        hostname = None
                        try:
                            hostname = socket.gethostbyaddr(ip_address)[0]
                        except:
                            pass
                        
                        devices.append(NetworkDevice(
                            mac_address=mac_address,
                            ip_address=ip_address,
                            hostname=hostname,
                            first_seen=int(time.time()),
                            last_seen=int(time.time())
                        ))
            
            # Update database and check for new devices
            existing_macs = {d.mac_address for d in self.db.get_devices()}
            
            for device in devices:
                is_new = device.mac_address not in existing_macs
                self.db.add_or_update_device(device)
                
                if is_new:
                    self.db.add_network_event('new_device', device.mac_address, device.ip_address, device.hostname)
                    
                    # Detect services on new device
                    services = await self.detect_services(device.ip_address)
                    
                    if services:
                        # Store detected services as vendor info
                        service_names = ', '.join([s['name'] for s in services])
                        device.vendor = f"Services: {service_names}"
                        self.db.add_or_update_device(device)
                        
                        # Send notification directly - no callback needed
                        if self.alert_new_devices:
                            try:
                                logger.info(f"ðŸš€ Sending notification for device with services")
                                await analytics_notify(
                                    'Network Scanner',
                                    'info',
                                    f"New device with services: {device.hostname or device.ip_address} - {service_names}"
                                )
                                logger.info(f"âœ… Notification sent successfully")
                            except Exception as e:
                                logger.error(f"âŒ Failed to send notification: {e}", exc_info=True)
                    else:
                        # Send notification directly - no callback needed
                        if self.alert_new_devices:
                            try:
                                logger.info(f"ðŸš€ Sending notification for device without services")
                                await analytics_notify(
                                    'Network Scanner',
                                    'info',
                                    f"New device discovered: {device.hostname or device.ip_address} ({device.mac_address})"
                                )
                                logger.info(f"âœ… Notification sent successfully")
                            except Exception as e:
                                logger.error(f"âŒ Failed to send notification: {e}", exc_info=True)
        
        finally:
            self.scanning = False
        
        return devices
    
    async def monitor_loop(self):
        """Continuous monitoring loop"""
        while self.monitoring:
            try:
                await self.scan_network()
                await asyncio.sleep(self.monitor_interval)
            except Exception as e:
                logger.error(f"Network monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def start_monitoring(self):
        """Start continuous network monitoring"""
        if not self.monitoring:
            self.monitoring = True
            self._monitor_task = asyncio.create_task(self.monitor_loop())
            logger.info("Network monitoring started")
    
    async def stop_monitoring(self):
        """Stop continuous network monitoring"""
        if self.monitoring:
            self.monitoring = False
            if self._monitor_task:
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
            logger.info("Network monitoring stopped")


# Global instances
db: Optional[AnalyticsDB] = None
monitor: Optional[HealthMonitor] = None
scanner: Optional[NetworkScanner] = None


def _json(data, status=200):
    """Helper to create JSON response"""
    return web.json_response(data, status=status)


# ============================
# API Routes
# ============================

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
        
        # Calculate uptime for this service
        metrics = db.get_metrics(service['service_name'], hours=24)
        if metrics:
            up_count = sum(1 for m in metrics if m.status == 'up')
            uptime_pct = (up_count / len(metrics)) * 100 if metrics else 100
            total_score += uptime_pct
        else:
            total_score += 100
    
    avg_score = total_score / enabled_count if enabled_count > 0 else 100
    
    return _json({
        'health_score': round(avg_score, 1),
        'status': 'healthy' if avg_score >= 95 else 'degraded' if avg_score >= 75 else 'critical',
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
    """Add a new service to monitor"""
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    required = ['service_name', 'endpoint', 'check_type']
    if not all(k in data for k in required):
        return _json({"error": "missing required fields"}, status=400)
    
    service = HealthCheck(
        service_name=data['service_name'],
        endpoint=data['endpoint'],
        check_type=data['check_type'],
        expected_status=data.get('expected_status', 200),
        timeout=data.get('timeout', 5),
        interval=data.get('interval', 60),
        enabled=data.get('enabled', True),
        retries=data.get('retries', 3),
        flap_window=data.get('flap_window', 3600),
        flap_threshold=data.get('flap_threshold', 5),
        suppression_duration=data.get('suppression_duration', 3600)
    )
    
    db.add_service(service)
    
    # Start monitoring if enabled
    if service.enabled and monitor:
        task = asyncio.create_task(monitor.monitor_service(service))
        monitor.monitoring_tasks[service.service_name] = task
    
    return _json({'success': True, 'service': data})


async def get_service(request: web.Request):
    """Get a specific service by ID"""
    service_id = int(request.match_info["service_id"])
    service = db.get_service(service_id)
    
    if not service:
        return _json({"error": "service not found"}, status=404)
    
    # service is already a dict from db.get_service()
    return _json(service)


async def update_service(request: web.Request):
    """Update a service"""
    service_id = int(request.match_info["service_id"])
    
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    service = db.get_service(service_id)
    if not service:
        return _json({"error": "service not found"}, status=404)
    
    # service is a dict, access with ['key']
    # Update service fields
    updated_service = HealthCheck(
        service_name=data.get('service_name', service['service_name']),
        endpoint=data.get('endpoint', service['endpoint']),
        check_type=data.get('check_type', service['check_type']),
        expected_status=data.get('expected_status', service['expected_status']),
        timeout=data.get('timeout', service['timeout']),
        interval=data.get('interval', service['check_interval']),
        enabled=data.get('enabled', service['enabled']),
        retries=data.get('retries', service.get('retries', 3)),
        flap_window=data.get('flap_window', service.get('flap_window', 3600)),
        flap_threshold=data.get('flap_threshold', service.get('flap_threshold', 5)),
        suppression_duration=data.get('suppression_duration', service.get('suppression_duration', 3600))
    )
    
    db.add_service(updated_service)
    
    # Restart monitoring task if it exists
    if monitor and service['service_name'] in monitor.monitoring_tasks:
        monitor.monitoring_tasks[service['service_name']].cancel()
        task = asyncio.create_task(monitor.monitor_service(updated_service))
        monitor.monitoring_tasks[service['service_name']] = task
    
    return _json({'success': True})


async def delete_service_route(request: web.Request):
    """Delete a service"""
    service_id = int(request.match_info["service_id"])
    service = db.get_service(service_id)
    
    if not service:
        return _json({"error": "service not found"}, status=404)
    
    # Stop monitoring task (service is a dict)
    if monitor and service['service_name'] in monitor.monitoring_tasks:
        monitor.monitoring_tasks[service['service_name']].cancel()
        del monitor.monitoring_tasks[service['service_name']]
    
    db.delete_service(service_id)
    
    return _json({'success': True})


async def get_uptime(request: web.Request):
    """Get uptime statistics for a service"""
    service_name = request.match_info["service_name"]
    
    try:
        hours = int(request.rel_url.query.get('hours', 24))
    except Exception:
        hours = 24
    
    metrics = db.get_metrics(service_name, hours)
    
    if not metrics:
        return _json({
            'service_name': service_name,
            'uptime_percentage': 0,
            'total_checks': 0,
            'successful_checks': 0,
            'failed_checks': 0
        })
    
    total_checks = len(metrics)
    successful_checks = sum(1 for m in metrics if m.status == 'up')
    uptime_percentage = (successful_checks / total_checks) * 100
    
    return _json({
        'service_name': service_name,
        'uptime_percentage': round(uptime_percentage, 2),
        'total_checks': total_checks,
        'successful_checks': successful_checks,
        'failed_checks': total_checks - successful_checks,
        'metrics': [
            {
                'timestamp': m.timestamp,
                'status': m.status,
                'response_time': m.response_time,
                'error_message': m.error_message
            }
            for m in metrics
        ]
    })


async def get_incidents(request: web.Request):
    """Get incidents - PATCHED to handle consistent format"""
    service_name = request.rel_url.query.get('service_name')
    
    try:
        hours = int(request.rel_url.query.get('hours', 168))
    except Exception:
        hours = 168
    
    return _json(db.get_incidents(service_name, hours))


async def reset_health_score(request: web.Request):
    """Reset health score by purging old metrics"""
    try:
        days = int(request.rel_url.query.get('days', 30))
    except Exception:
        days = 30
    
    deleted = db.purge_old_metrics(days)
    return _json({'success': True, 'deleted_metrics': deleted})


async def reset_incidents(request: web.Request):
    """Clear ALL incidents (not just old ones)"""
    conn = sqlite3.connect(db.db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM analytics_incidents")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    
    return _json({'success': True, 'deleted_incidents': deleted})


async def reset_service_data(request: web.Request):
    """Reset all data for a specific service"""
    service_name = request.match_info["service_name"]
    
    metrics_deleted = db.reset_service_metrics(service_name)
    incidents_deleted = db.reset_service_incidents(service_name)
    
    return _json({
        'success': True,
        'deleted_metrics': metrics_deleted,
        'deleted_incidents': incidents_deleted
    })


async def purge_all_metrics(request: web.Request):
    """Purge ALL metrics AND incidents (complete reset)"""
    conn = sqlite3.connect(db.db_path)
    cur = conn.cursor()
    
    cur.execute("DELETE FROM analytics_metrics")
    metrics_deleted = cur.rowcount
    
    cur.execute("DELETE FROM analytics_incidents")
    incidents_deleted = cur.rowcount
    
    conn.commit()
    conn.close()
    
    return _json({
        'success': True, 
        'deleted_metrics': metrics_deleted,
        'deleted_incidents': incidents_deleted
    })


async def purge_week_metrics(request: web.Request):
    """Purge metrics older than 1 week"""
    deleted = db.purge_old_metrics(7)
    return _json({'success': True, 'deleted_metrics': deleted})


async def purge_month_metrics(request: web.Request):
    """Purge metrics older than 1 month"""
    deleted = db.purge_old_metrics(30)
    return _json({'success': True, 'deleted_metrics': deleted})


# Network monitoring routes

async def network_scan(request: web.Request):
    """Trigger a network scan"""
    devices = await scanner.scan_network()
    
    return _json({
        'success': True,
        'devices_found': len(devices),
        'devices': [
            {
                'mac_address': d.mac_address,
                'ip_address': d.ip_address,
                'hostname': d.hostname,
                'vendor': d.vendor
            }
            for d in devices
        ]
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
           service_name = custom_name or hostname or f"Device-{ip_address}"

    # --- SAFETY PATCH: prevent undefined service names ---
    if not service_name or str(service_name).strip().lower() in ("", "none", "null", "undefinedservice"):
        service_name = f"Device-{ip_address or 'unknown'}"
    # -----------------------------------------------------
            
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


async def detect_device_services(request: web.Request):
    """Detect services on a specific device"""
    mac_address = request.match_info["mac_address"]
    
    device = db.get_device(mac_address)
    if not device:
        return _json({"error": "Device not found"}, status=404)
    
    if not device.get('ip_address'):
        return _json({"error": "Device has no IP address"}, status=400)
    
    # Detect services
    services = await scanner.detect_services(device['ip_address'])
    
    if services:
        # Update device vendor with detected services
        service_names = ', '.join([s['name'] for s in services])
        db.update_device_settings(mac_address, custom_name=f"{device.get('custom_name', '')} [{service_names}]".strip())
    
    return _json({
        'success': True,
        'services': services,
        'device': device
    })


async def scan_all_services(request: web.Request):
    """Scan all known devices for services"""
    devices = db.get_all_devices()
    results = []
    
    for device in devices:
        if device.get('ip_address'):
            services = await scanner.detect_services(device['ip_address'])
            if services:
                results.append({
                    'mac_address': device['mac_address'],
                    'ip_address': device['ip_address'],
                    'hostname': device.get('hostname'),
                    'services': services
                })
    
    return _json({
        'success': True,
        'scanned': len(devices),
        'found': len(results),
        'results': results
    })


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
    app.router.add_post('/api/analytics/network/devices/{mac_address}/detect', detect_device_services)
    app.router.add_post('/api/analytics/network/scan-services', scan_all_services)



async def analytics_notify(source: str, level: str, message: str):
    """
    Analytics notification handler
    """
    title = f"Analytics â€” {source}"
    body = f"[{level.upper()}] {message}"
    priority = 5 if level.lower() in ("critical", "error", "down") else 3
    
    logger.info(f"ðŸ“¤ analytics_notify START: {title}")
    logger.info(f"   Message: {body}")
    
    # Try to import and use process_incoming
    try:
        logger.info(f"   Attempting to import process_incoming from bot...")
        from bot import process_incoming
        logger.info(f"   âœ… Import successful! Function type: {type(process_incoming)}")
        logger.info(f"   Is coroutine function: {asyncio.iscoroutinefunction(process_incoming)}")
        
        # Call it
        try:
            if asyncio.iscoroutinefunction(process_incoming):
                logger.info(f"   Calling as async function...")
                await process_incoming(title, body, source="analytics", priority=priority)
            else:
                logger.info(f"   Calling as sync function via executor...")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, 
                    lambda: process_incoming(title, body, source="analytics", priority=priority)
                )
            
            logger.info(f"âœ… process_incoming completed successfully")
            logger.info(f"âœ… Fan-out should be complete - check inbox/Gotify/UI")
            
        except Exception as call_error:
            logger.error(f"âŒ Error calling process_incoming: {call_error}", exc_info=True)
            logger.error(f"   This means process_incoming exists but threw an error")
            
    except ImportError as import_error:
        logger.error(f"âŒ Cannot import process_incoming from bot: {import_error}")
        logger.error(f"   This means bot.py doesn't have process_incoming function")
        logger.error(f"   Notification will ONLY appear in analytics inbox")
    except Exception as e:
        logger.error(f"âŒ Unexpected error in analytics_notify: {e}", exc_info=True)








async def init_analytics(app: web.Application, notification_callback: Optional[Callable] = None):
    """Initialize analytics module"""
    global db, monitor, scanner
    
    db = AnalyticsDB()
    
    # Use provided callback or default
    callback = notification_callback or analytics_notify
    
    logger.info(f"[analytics] Initializing with callback: {callback.__name__ if hasattr(callback, '__name__') else type(callback)}")
    
    monitor = HealthMonitor(db, callback)
    scanner = NetworkScanner(db)
    scanner.set_notification_callback(callback)
    
    logger.info(f"[analytics] Scanner callback set: {scanner.notification_callback is not None}")
    
    # Start monitoring all enabled services
    await monitor.start_all()
    
    logger.info("Analytics module initialized with network monitoring")


async def shutdown_analytics():
    """Shutdown analytics module"""
    if monitor:
        await monitor.stop_all()
    if scanner:
        await scanner.stop_monitoring()
