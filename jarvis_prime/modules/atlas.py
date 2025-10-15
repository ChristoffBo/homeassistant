#!/usr/bin/env python3
# /app/atlas.py
# Jarvis Prime - Atlas Module (Backend)
# Enhanced edition — color mapping, caching, group aggregation, latency stats, URL links, structured logging, alive flag.

import json
import re
import sqlite3
import logging
import time
import statistics
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


def build_topology_snapshot() -> dict:
    """Core builder with enhancements."""
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

    # --- hosts ---
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
        ensure_node(
            sname,
            type="service",
            status=status,
            last_checked=last_ts,
            latency=latency,
            color=col,
            severity=sev,
            alive=status.lower() in ("up", "ok"),
            url=f"/analytics?service={sname}"
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
        }
        if n.ip: d["ip"] = n.ip
        if n.group: d["group"] = n.group
        if n.description: d["description"] = n.description
        if n.last_checked is not None: d["last_checked"] = n.last_checked
        if n.latency is not None: d["latency"] = n.latency
        if n.url: d["url"] = n.url
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
        },
        "groups": group_counts,
        "latency_stats": {"avg": avg_lat, "median": med_lat},
    }

    _cache.update({"ts": now, "payload": payload})
    logger.info("[atlas] snapshot built: %d nodes, %d links", len(nodes), len(links))
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
    return _json({"atlas": "ok"})


def register_routes(app: web.Application):
    """Mount Atlas routes onto the aiohttp app."""
    app.router.add_get("/api/atlas/topology", api_topology)
    app.router.add_get("/api/atlas/ping", api_ping)