#!/usr/bin/env python3
# /app/atlas.py
# Jarvis Prime - Atlas Module (Backend)
# Enhanced edition with WebUI click-to-open functionality

import json
import re
import sqlite3
import logging
import time
import statistics
import asyncio
import aiohttp
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from aiohttp import web

logger = logging.getLogger("atlas")
logger.setLevel(logging.INFO)

DB_PATH = "/data/jarvis.db"

# --- internal cache (5 s TTL) ---
_cache = {"ts": 0.0, "payload": None}
_CACHE_TTL = 5.0

# WebUI check cache (15 min TTL)
_webui_cache: Dict[str, dict] = {}
_WEBUI_CACHE_TTL = 900.0


# ==============================
# Utilities
# ==============================
def safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="ignore")
    return str(val)


def extract_host(endpoint: str) -> str:
    """Extract hostname/IP from any endpoint form."""
    if not endpoint:
        return ""
    endpoint = endpoint.strip()
    try:
        p = urlparse(endpoint if "://" in endpoint else f"//{endpoint}", scheme="")
        host = p.hostname or ""
        if host:
            return host
    except Exception:
        pass
    m = re.match(r"^\[?([A-Za-z0-9\.\-\:]+)\]?(?::\d+)?$", endpoint)
    return m.group(1) if m else endpoint


# ==============================
# WebUI Detection & Health Check
# ==============================
async def check_webui_exists(ip: str, node_name: str) -> dict:
    """
    Check if device has accessible WebUI.
    Returns: {has_webui, webui_url, requires_auth, check_method}
    """
    cache_key = f"{ip}:{node_name}"
    now = time.time()
    
    # Return cached result if fresh
    if cache_key in _webui_cache:
        cached = _webui_cache[cache_key]
        if now - cached.get("timestamp", 0) < _WEBUI_CACHE_TTL:
            return cached
    
    result = {
        "has_webui": False,
        "webui_url": None,
        "requires_auth": False,
        "check_method": None,
        "timestamp": now
    }
    
    if not ip:
        _webui_cache[cache_key] = result
        return result
    
    # Common WebUI endpoints to check
    endpoints = [
        (f"http://{ip}", "root"),
        (f"http://{ip}/admin", "admin_path"),
        (f"https://{ip}", "root_https"),
        (f"http://{ip}:8080", "alt_port_8080"),
        (f"http://{ip}:8123", "home_assistant"),
        (f"http://{ip}:9090", "prometheus"),
        (f"http://{ip}:3000", "grafana"),
        (f"http://{ip}:5000", "generic_5000"),
        (f"http://{ip}:80/admin", "pi_hole"),
    ]
    
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url, method in endpoints:
            try:
                async with session.get(
                    url,
                    allow_redirects=True,
                    ssl=False  # Allow self-signed certs
                ) as response:
                    # 200 = accessible WebUI
                    # 401/403 = WebUI exists but needs auth
                    # 301/302 = redirect (likely WebUI)
                    if response.status in [200, 301, 302, 401, 403]:
                        result["has_webui"] = True
                        result["webui_url"] = url
                        result["requires_auth"] = response.status in [401, 403]
                        result["check_method"] = method
                        logger.info(f"[atlas] WebUI found for {node_name} at {url} (status: {response.status})")
                        break
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug(f"[atlas] WebUI check failed for {url}: {e}")
                continue
    
    _webui_cache[cache_key] = result
    return result


# ==============================
# DB access (read-only)
# ==============================
def q(conn: sqlite3.Connection, query: str, params: Tuple = ()) -> List[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    return [dict(r) for r in cur.fetchall()]


def fetch_orchestrator_hosts(conn: sqlite3.Connection) -> List[dict]:
    return q(conn, """
        SELECT id, name, hostname, port, username, groups, description, updated_at
        FROM orchestration_servers
        ORDER BY name ASC
    """)


def fetch_analytics_services(conn: sqlite3.Connection) -> List[dict]:
    return q(conn, """
        SELECT id, service_name, endpoint, check_type, expected_status,
               timeout, check_interval, enabled
        FROM analytics_services
        ORDER BY service_name ASC
    """)


def fetch_latest_status_by_service(conn: sqlite3.Connection) -> Dict[str, dict]:
    rows = q(conn, """
        SELECT m.service_name, m.status, m.timestamp, m.response_time, m.error_message
        FROM analytics_metrics m
        JOIN (
            SELECT service_name, MAX(timestamp) AS max_ts
            FROM analytics_metrics
            GROUP BY service_name
        ) latest
        ON latest.service_name = m.service_name AND latest.max_ts = m.timestamp
    """)
    out = {}
    for r in rows:
        svc = safe_str(r.get("service_name"))
        out[svc] = {
            "status": safe_str(r.get("status", "unknown")),
            "timestamp": r.get("timestamp"),
            "response_time": r.get("response_time"),
            "error_message": safe_str(r.get("error_message")) if r.get("error_message") else None,
        }
    return out


# ==============================
# Topology build
# ==============================
@dataclass
class Node:
    id: str
    type: str               # core | host | service
    status: str = "unknown"
    ip: Optional[str] = None
    group: Optional[str] = None
    description: Optional[str] = None
    last_checked: Optional[int] = None
    latency: Optional[float] = None
    alive: Optional[bool] = None
    color: Optional[str] = None
    severity: Optional[str] = None
    url: Optional[str] = None
    webui_url: Optional[str] = None
    has_webui: bool = False
    requires_auth: bool = False


_COLOR_MAP = {
    "up":   ("#00C853", "good"),
    "ok":   ("#00C853", "good"),
    "down": ("#D50000", "critical"),
    "fail": ("#D50000", "critical"),
    "unknown": ("#9E9E9E", "unknown"),
}


def _status_color(status: str) -> Tuple[str, str]:
    s = (status or "").lower()
    return _COLOR_MAP.get(s, _COLOR_MAP["unknown"])


async def build_topology_snapshot_async() -> dict:
    """Async version with WebUI detection."""
    now = time.time()
    if _cache["payload"] and now - _cache["ts"] < _CACHE_TTL:
        logger.debug("[atlas] returning cached snapshot")
        return _cache["payload"]

    with sqlite3.connect(DB_PATH) as conn:
        hosts = fetch_orchestrator_hosts(conn)
        services = fetch_analytics_services(conn)
        latest = fetch_latest_status_by_service(conn)

    logger.info("[atlas] building snapshot: %d hosts, %d services", len(hosts), len(services))

    host_by_hostname: Dict[str, dict] = {}
    host_by_name_ci: Dict[str, dict] = {}
    for h in hosts:
        hn = safe_str(h["hostname"]).strip()
        if hn:
            host_by_hostname[hn.lower()] = h
        host_by_name_ci[safe_str(h["name"]).lower()] = h

    nodes: Dict[str, Node] = {}
    links: List[dict] = []

    def ensure_node(node_id: str, **kwargs) -> Node:
        if node_id in nodes:
            n = nodes[node_id]
            for k, v in kwargs.items():
                if getattr(n, k, None) in (None, "unknown") and v not in (None, "unknown"):
                    setattr(n, k, v)
            return n
        n = Node(id=node_id, **kwargs)
        nodes[node_id] = n
        return n

    # Core
    ensure_node("Jarvis_Prime", type="core", status="up", alive=True, color="#00C853", severity="good")

    # --- hosts with WebUI detection ---
    webui_checks = []
    for h in hosts:
        name = safe_str(h["name"])
        host_ip = safe_str(h["hostname"])
        group = safe_str(h.get("groups", "")) or None
        desc = safe_str(h.get("description", "")) or None
        col, sev = _status_color("unknown")
        ensure_node(
            name,
            type="host",
            ip=host_ip,
            group=group,
            description=desc,
            color=col,
            severity=sev,
            alive=False,
            url=f"/orchestrator?host={name}"
        )
        links.append({"source": "Jarvis_Prime", "target": name})
        
        # Queue WebUI check
        if host_ip:
            webui_checks.append((name, host_ip))
    
    # Run all WebUI checks concurrently
    if webui_checks:
        webui_results = await asyncio.gather(
            *[check_webui_exists(ip, name) for name, ip in webui_checks],
            return_exceptions=True
        )
        
        for (name, ip), result in zip(webui_checks, webui_results):
            if isinstance(result, Exception):
                logger.warning(f"[atlas] WebUI check failed for {name}: {result}")
                continue
            
            if result.get("has_webui"):
                node = nodes.get(name)
                if node:
                    node.webui_url = result["webui_url"]
                    node.has_webui = True
                    node.requires_auth = result["requires_auth"]

    # --- services ---
    for svc in services:
        sname = safe_str(svc["service_name"])
        endpoint = safe_str(svc["endpoint"])
        host_part = extract_host(endpoint).lower()
        status_blob = latest.get(sname, {})
        status = status_blob.get("status", "unknown")
        last_ts = status_blob.get("timestamp")
        latency = status_blob.get("response_time")

        parent_host_obj = None
        if host_part and host_part in host_by_hostname:
            parent_host_obj = host_by_hostname[host_part]
        elif sname.lower() in host_by_name_ci:
            parent_host_obj = host_by_name_ci[sname.lower()]

        # Host-check merge
        is_host_check = False
        if parent_host_obj is not None:
            check_type = safe_str(svc.get("check_type"))
            if check_type in ("ping",) or sname.lower() == safe_str(parent_host_obj["name"]).lower():
                is_host_check = True

        if is_host_check and parent_host_obj is not None:
            host_name = safe_str(parent_host_obj["name"])
            col, sev = _status_color(status)
            ensure_node(
                host_name,
                type="host",
                status=status,
                last_checked=last_ts,
                latency=latency,
                color=col,
                severity=sev,
                alive=status.lower() in ("up", "ok"),
            )
            continue

        # service node
        parent_name = None
        if parent_host_obj is not None:
            parent_name = safe_str(parent_host_obj["name"])
        col, sev = _status_color(status)
        
        # Services can have WebUI too (e.g., web services)
        service_webui = None
        if endpoint and status.lower() in ("up", "ok"):
            service_webui = endpoint if endpoint.startswith("http") else None
        
        ensure_node(
            sname,
            type="service",
            status=status,
            last_checked=last_ts,
            latency=latency,
            color=col,
            severity=sev,
            alive=status.lower() in ("up", "ok"),
            url=f"/analytics?service={sname}",
            webui_url=service_webui,
            has_webui=bool(service_webui)
        )

        links.append({
            "source": parent_name or "Jarvis_Prime",
            "target": sname
        })

    # --- group + latency stats ---
    group_counts: Dict[str, int] = {}
    latencies: List[float] = []
    for n in nodes.values():
        if n.group:
            group_counts[n.group] = group_counts.get(n.group, 0) + 1
        if isinstance(n.latency, (int, float)):
            latencies.append(float(n.latency))

    avg_lat = statistics.mean(latencies) if latencies else None
    med_lat = statistics.median(latencies) if latencies else None

    def node_to_dict(n: Node) -> dict:
        d = {
            "id": n.id,
            "type": n.type,
            "status": n.status,
            "alive": bool(n.alive),
            "color": n.color,
            "severity": n.severity,
            "has_webui": n.has_webui,
        }
        if n.ip: d["ip"] = n.ip
        if n.group: d["group"] = n.group
        if n.description: d["description"] = n.description
        if n.last_checked is not None: d["last_checked"] = n.last_checked
        if n.latency is not None: d["latency"] = n.latency
        if n.url: d["url"] = n.url
        if n.webui_url: d["webui_url"] = n.webui_url
        if n.requires_auth: d["requires_auth"] = n.requires_auth
        return d

    payload = {
        "timestamp": now,
        "nodes": [node_to_dict(n) for n in nodes.values()],
        "links": links,
        "counts": {
            "hosts": sum(1 for n in nodes.values() if n.type == "host"),
            "services": sum(1 for n in nodes.values() if n.type == "service"),
            "total_nodes": len(nodes),
            "total_links": len(links),
            "webui_enabled": sum(1 for n in nodes.values() if n.has_webui),
        },
        "groups": group_counts,
        "latency_stats": {"avg": avg_lat, "median": med_lat},
    }

    _cache.update({"ts": now, "payload": payload})
    logger.info("[atlas] snapshot built: %d nodes, %d links, %d with WebUI", 
                len(nodes), len(links), payload["counts"]["webui_enabled"])
    return payload


def build_topology_snapshot() -> dict:
    """Sync wrapper for async build."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(build_topology_snapshot_async())


# ==============================
# HTTP API
# ==============================
def _json(data, status=200):
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json"
    )


async def api_topology(request: web.Request):
    try:
        payload = await build_topology_snapshot_async()
        return _json(payload, 200)
    except Exception as e:
        logger.exception("[atlas] topology build failed")
        return _json({"error": str(e)}, 500)


async def api_ping(request: web.Request):
    return _json({"atlas": "ok"})


def register_routes(app: web.Application):
    """Mount Atlas routes onto the aiohttp app."""
    app.router.add_get("/api/atlas/topology", api_topology)
    app.router.add_get("/api/atlas/ping", api_ping)
