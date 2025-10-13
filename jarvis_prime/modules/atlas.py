#!/usr/bin/env python3
# /app/atlas.py
# Jarvis Prime - Atlas Module (Backend)
# Purpose: Build a live topology from Orchestrator + Analytics without any background load.
# - Read-only against /data/jarvis.db
# - No WebSocket loop; zero impact when the Atlas tab is closed
# - Single endpoint: GET /api/atlas/topology
# - Jarvis_Prime always at the center
# - Dedup hosts across Orchestrator + Analytics (auto-merge if Analytics entry is a host check)
# - Services attach to their parent host via hostname/IP matching; orphans attach to Jarvis_Prime
# - Names are taken AS-IS from Orchestrator.name and Analytics.service_name

import json
import re
import sqlite3
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from aiohttp import web

logger = logging.getLogger(__name__)

DB_PATH = "/data/jarvis.db"


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
    """
    Extract a hostname/IP from various endpoint formats:
    - http(s)://10.0.0.21:32400/path
    - 10.0.0.21:32400
    - 10.0.0.21
    - myhost.local
    """
    if not endpoint:
        return ""
    endpoint = endpoint.strip()

    # Try URL parse first
    try:
        p = urlparse(endpoint if "://" in endpoint else f"//{endpoint}", scheme="")
        # urlparse with // will put host in 'netloc'
        host = p.hostname or ""
        if host:
            return host
    except Exception:
        pass

    # Fallback regex for host:port
    m = re.match(r"^\[?([A-Za-z0-9\.\-\:]+)\]?(?::\d+)?$", endpoint)
    if m:
        return m.group(1)

    return endpoint


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
        SELECT
            id, name, hostname, port, username, groups, description, updated_at
        FROM orchestration_servers
        ORDER BY name ASC
    """)


def fetch_analytics_services(conn: sqlite3.Connection) -> List[dict]:
    # Pull configured services
    return q(conn, """
        SELECT
            id,
            service_name,
            endpoint,
            check_type,
            expected_status,
            timeout,
            check_interval,
            enabled
        FROM analytics_services
        ORDER BY service_name ASC
    """)


def fetch_latest_status_by_service(conn: sqlite3.Connection) -> Dict[str, dict]:
    """
    Return a mapping: service_name -> {status, timestamp, response_time, error_message}
    from the most recent analytics_metrics row for each service.
    """
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
        out[safe_str(r["service_name"])] = {
            "status": safe_str(r.get("status", "unknown")),
            "timestamp": r.get("timestamp"),
            "response_time": r.get("response_time"),
            "error_message": safe_str(r.get("error_message")) if r.get("error_message") is not None else None
        }
    return out


# ==============================
# Topology build
# ==============================

@dataclass
class Node:
    id: str
    type: str  # core | host | service
    status: str = "unknown"
    ip: Optional[str] = None
    group: Optional[str] = None
    description: Optional[str] = None
    last_checked: Optional[int] = None
    latency: Optional[float] = None


def build_topology_snapshot() -> dict:
    """
    Core builder: merges Orchestrator + Analytics into a clean graph.
    - Jarvis_Prime at center
    - Hosts from Orchestrator (unique by hostname/ip)
    - Analytics entries:
        * If endpoint host matches a known Orchestrator host -> attach as service under that host
        * If service appears to be a host-check (endpoint host equals an Orchestrator hostname,
          OR service_name equals a server name case-insensitive) -> merge status into that host (no extra node)
        * If no match -> attach service directly to Jarvis_Prime
    """
    with sqlite3.connect(DB_PATH) as conn:
        # Collect DB data
        hosts = fetch_orchestrator_hosts(conn)
        services = fetch_analytics_services(conn)
        latest = fetch_latest_status_by_service(conn)

    # Build lookup maps
    # Orchestrator hostnames normalized (case-insensitive)
    host_by_hostname: Dict[str, dict] = {}
    host_by_name_ci: Dict[str, dict] = {}
    for h in hosts:
        hn = safe_str(h["hostname"]).strip()
        if hn:
            host_by_hostname[hn.lower()] = h
        host_by_name_ci[safe_str(h["name"]).lower()] = h

    # Initialize node set with core
    nodes: Dict[str, Node] = {}
    links: List[dict] = []

    def ensure_node(node_id: str, **kwargs) -> Node:
        if node_id in nodes:
            # Patch in any new fields that arrive later
            n = nodes[node_id]
            for k, v in kwargs.items():
                if getattr(n, k, None) in (None, "unknown") and v not in (None, "unknown"):
                    setattr(n, k, v)
            return n
        n = Node(id=node_id, **kwargs)
        nodes[node_id] = n
        return n

    # Core
    ensure_node("Jarvis_Prime", type="core", status="up")

    # Add hosts from Orchestrator (always shown)
    for h in hosts:
        name = safe_str(h["name"])
        host_ip = safe_str(h["hostname"])
        group = safe_str(h.get("groups", "")) if h.get("groups") is not None else None
        desc = safe_str(h.get("description", "")) if h.get("description") is not None else None

        ensure_node(name, type="host", ip=host_ip or None, group=group, description=desc)
        links.append({"source": "Jarvis_Prime", "target": name})

    # Attach analytics services/host-checks
    for svc in services:
        sname = safe_str(svc["service_name"])
        endpoint = safe_str(svc["endpoint"])
        host_part = extract_host(endpoint).lower()
        status_blob = latest.get(sname, {})
        status = status_blob.get("status", "unknown")
        last_ts = status_blob.get("timestamp")
        latency = status_blob.get("response_time")

        # Try to find parent host by endpoint host or by service_name matching a host name
        parent_host_obj = None
        if host_part and host_part in host_by_hostname:
            parent_host_obj = host_by_hostname[host_part]
        elif sname.lower() in host_by_name_ci:
            parent_host_obj = host_by_name_ci[sname.lower()]

        # If this Analytics entry is a host-check (i.e., represents the host itself),
        # then merge status into the host node rather than creating a child node.
        is_host_check = False
        if parent_host_obj is not None:
            # It's a host check if the service appears to be checking the host directly,
            # e.g., check_type == 'ping' or endpoint host matches the host's IP/hostname exactly,
            # or the service name equals the host name.
            check_type = safe_str(svc.get("check_type"))
            if check_type in ("ping",) or sname.lower() == safe_str(parent_host_obj["name"]).lower():
                is_host_check = True

        if is_host_check and parent_host_obj is not None:
            host_name = safe_str(parent_host_obj["name"])
            # Update existing host node status/last_checked/latency
            ensure_node(
                host_name,
                type="host",
                status=status,
                last_checked=last_ts,
                latency=latency,
            )
            # No separate service node
            continue

        # Not a direct host-check: create/attach service node
        parent_name: Optional[str] = None
        if parent_host_obj is not None:
            parent_name = safe_str(parent_host_obj["name"])

        # Create service node
        ensure_node(
            sname,
            type="service",
            status=status,
            last_checked=last_ts,
            latency=latency,
        )

        # Link appropriately
        if parent_name:
            links.append({"source": parent_name, "target": sname})
        else:
            # Orphan - attach to Jarvis_Prime
            links.append({"source": "Jarvis_Prime", "target": sname})

    # Build final payload
    def node_to_dict(n: Node) -> dict:
        d = {
            "id": n.id,
            "type": n.type,
            "status": n.status,
        }
        if n.ip:
            d["ip"] = n.ip
        if n.group:
            d["group"] = n.group
        if n.description:
            d["description"] = n.description
        if n.last_checked is not None:
            d["last_checked"] = n.last_checked
        if n.latency is not None:
            d["latency"] = n.latency
        return d

    payload = {
        "timestamp": __import__("time").time(),
        "nodes": [node_to_dict(n) for n in nodes.values()],
        "links": links,
        "counts": {
            "hosts": sum(1 for n in nodes.values() if n.type == "host"),
            "services": sum(1 for n in nodes.values() if n.type == "service"),
            "total_nodes": len(nodes),
            "total_links": len(links),
        },
    }
    return payload


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
        payload = build_topology_snapshot()
        return _json(payload, 200)
    except Exception as e:
        logger.exception("[atlas] topology build failed")
        return _json({"error": str(e)}, 500)


async def api_ping(request: web.Request):
    # Tiny health endpoint so you can quickly verify routes are live
    return _json({"atlas": "ok"})


def register_routes(app: web.Application):
    """
    Mount Atlas routes onto the existing aiohttp app without touching bot.py.
    Usage:
        from atlas import register_routes as register_atlas
        register_atlas(app)
    """
    app.router.add_get("/api/atlas/topology", api_topology)
    app.router.add_get("/api/atlas/ping", api_ping)