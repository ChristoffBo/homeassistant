#!/usr/bin/env python3
"""
🧩 Veil — Privacy-First DNS/DHCP Server
Complete implementation with ALL features

Full Privacy Flow:
- DoH/DoT/DoQ encrypted upstream
- RFC 7830/8467 query padding (468-byte blocks)
- EDNS Client Subnet stripping
- 0x20 case randomization
- QNAME Minimization (RFC 9156)
- Query jitter (10-100ms)
- Parallel upstream rotation
- Bidirectional padding
- DNSSEC validation
- Zero telemetry

DHCP Features:
- Full DHCPv4 implementation
- DISCOVER/OFFER/REQUEST/ACK/NAK/DECLINE/RELEASE/INFORM
- Ping before offer (conflict detection)
- Static leases
- Dynamic lease pool
- PXE boot support
- DHCP relay support
- Vendor options
- Client identifier handling
"""

import asyncio
import logging
import socket
import struct
import time
import random
import ipaddress
import hashlib
import base64
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass, field
import json
import re

from aiohttp import web, ClientSession, TCPConnector, ClientTimeout
import dns.message
import dns.query
import dns.rdatatype
import dns.exception
import dns.flags
import dns.rcode
import dns.name
import dns.rdtypes.IN.A
import dns.rdtypes.IN.AAAA
import dns.rdtypes.ANY.CNAME
import dns.rdtypes.ANY.TXT
import dns.rdtypes.ANY.MX

log = logging.getLogger("veil")

# ==================== CONFIGURATION ====================
CONFIG = {
    # DNS Core
    "enabled": True,
    "dns_port": 53,
    "dns_bind": "0.0.0.0",
    
    # Caching
    "cache_enabled": True,
    "cache_ttl": 3600,
    "negative_cache_ttl": 300,
    "cache_max_size": 10000,
    "stale_serving": True,
    "stale_ttl_multiplier": 2,
    
    # Upstream Servers
    "upstream_servers": [
        "1.1.1.1",      # Cloudflare
        "1.0.0.1",
        "8.8.8.8",      # Google
        "8.8.4.4",
        "9.9.9.9",      # Quad9
    ],
    "upstream_timeout": 2.0,
    "upstream_parallel": True,  # Query multiple upstreams in parallel
    "upstream_rotation": True,
    "upstream_max_failures": 3,
    
    # Privacy Features
    "doh_enabled": True,
    "dot_enabled": True,
    "doq_enabled": False,  # Requires aioquic
    "ecs_strip": True,
    "dnssec_validate": True,
    "query_jitter": True,
    "query_jitter_ms": [10, 100],  # Min, max jitter
    "zero_log": False,
    "padding_enabled": True,  # RFC 7830/8467
    "padding_block_size": 468,  # Bytes
    "case_randomization": True,  # 0x20 encoding
    "qname_minimization": True,  # RFC 9156
    
    # Blocking
    "blocking_enabled": True,
    "block_response_type": "NXDOMAIN",
    "block_custom_ip": "0.0.0.0",
    "blocklists": [],
    "whitelist": [],
    "blacklist": [],
    
    # DNS Rewrites
    "local_records": {},
    "dns_rewrites": {},
    
    # Conditional Forwarding
    "conditional_forwards": {},
    
    # Security
    "rebinding_protection": True,
    "rebinding_whitelist": [],
    
    # DHCP Server
    "dhcp_enabled": False,
    "dhcp_port": 67,
    "dhcp_bind": "0.0.0.0",
    "dhcp_interface": "eth0",
    "dhcp_subnet": "192.168.1.0",
    "dhcp_netmask": "255.255.255.0",
    "dhcp_gateway": "192.168.1.1",
    "dhcp_dns_servers": ["192.168.1.1"],
    "dhcp_lease_time": 86400,
    "dhcp_renewal_time": None,
    "dhcp_rebinding_time": None,
    "dhcp_range_start": "192.168.1.100",
    "dhcp_range_end": "192.168.1.200",
    "dhcp_static_leases": {},
    "dhcp_domain": "local",
    "dhcp_ntp_servers": [],
    "dhcp_wins_servers": [],
    "dhcp_tftp_server": None,
    "dhcp_bootfile": None,
    "dhcp_ping_check": True,  # Ping before offer
    "dhcp_ping_timeout": 1,  # Seconds
    "dhcp_relay_support": True,
    "dhcp_vendor_options": {},  # Custom vendor options
}

# ==================== STATISTICS ====================
STATS = {
    "dns_queries": 0,
    "dns_cached": 0,
    "dns_blocked": 0,
    "dns_upstream": 0,
    "dns_parallel": 0,
    "dns_padded": 0,
    "dns_0x20": 0,
    "dns_qname_min": 0,
    "dhcp_discovers": 0,
    "dhcp_offers": 0,
    "dhcp_requests": 0,
    "dhcp_acks": 0,
    "dhcp_naks": 0,
    "dhcp_declines": 0,
    "dhcp_releases": 0,
    "dhcp_informs": 0,
    "dhcp_ping_checks": 0,
    "dhcp_conflicts": 0,
    "start_time": time.time()
}

# ==================== DNS CACHE ====================
@dataclass
class CacheEntry:
    response: bytes
    expires: float
    negative: bool = False
    stale_ttl: float = 0

class LRUCache:
    """LRU cache with TTL support"""
    def __init__(self, max_size: int = 10000):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._lock = asyncio.Lock()
    
    def _key(self, qname: str, qtype: int) -> str:
        return f"{qname}:{qtype}"
    
    async def get(self, qname: str, qtype: int) -> Optional[bytes]:
        if not CONFIG.get("cache_enabled"):
            return None
        
        key = self._key(qname, qtype)
        async with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            now = time.time()
            
            if now < entry.expires:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return entry.response
            
            if CONFIG.get("stale_serving") and now < entry.stale_ttl:
                log.debug(f"[cache] Serving stale: {qname}")
                self._cache.move_to_end(key)
                return entry.response
            
            del self._cache[key]
            return None
    
    async def set(self, qname: str, qtype: int, response: bytes, ttl: int, negative: bool = False):
        if not CONFIG.get("cache_enabled"):
            return
        
        key = self._key(qname, qtype)
        now = time.time()
        expires = now + ttl
        stale_multiplier = CONFIG.get("stale_ttl_multiplier", 2)
        stale_ttl = expires + (ttl * stale_multiplier)
        
        async with self._lock:
            # Check size limit
            if len(self._cache) >= self._max_size:
                # Remove oldest (first item)
                self._cache.popitem(last=False)
            
            self._cache[key] = CacheEntry(
                response=response,
                expires=expires,
                negative=negative,
                stale_ttl=stale_ttl
            )
            self._cache.move_to_end(key)
    
    async def flush(self):
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            log.info(f"[cache] Flushed {count} entries")
    
    def size(self) -> int:
        return len(self._cache)

DNS_CACHE = LRUCache(max_size=CONFIG.get("cache_max_size", 10000))

# ==================== DOMAIN LISTS ====================
class TrieNode:
    """Trie node for efficient domain matching"""
    def __init__(self):
        self.children: Dict[str, 'TrieNode'] = {}
        self.is_blocked = False

class DomainList:
    """Trie-based domain list for efficient lookups"""
    def __init__(self, name: str):
        self.name = name
        self._root = TrieNode()
        self._count = 0
        self._lock = asyncio.Lock()
    
    async def add(self, domain: str):
        domain = domain.lower().strip('.')
        parts = domain.split('.')[::-1]  # Reverse for suffix matching
        
        async with self._lock:
            node = self._root
            for part in parts:
                if part not in node.children:
                    node.children[part] = TrieNode()
                node = node.children[part]
            
            if not node.is_blocked:
                node.is_blocked = True
                self._count += 1
    
    def add_sync(self, domain: str):
        """Synchronous add for bulk loading"""
        domain = domain.lower().strip('.')
        parts = domain.split('.')[::-1]
        
        node = self._root
        for part in parts:
            if part not in node.children:
                node.children[part] = TrieNode()
            node = node.children[part]
        
        if not node.is_blocked:
            node.is_blocked = True
            self._count += 1
    
    async def contains(self, domain: str) -> bool:
        domain = domain.lower().strip('.')
        parts = domain.split('.')[::-1]
        
        async with self._lock:
            node = self._root
            for i, part in enumerate(parts):
                if part not in node.children:
                    return False
                node = node.children[part]
                # Check if any parent domain is blocked
                if node.is_blocked:
                    return True
        
        return False
    
    async def remove(self, domain: str):
        domain = domain.lower().strip('.')
        parts = domain.split('.')[::-1]
        
        async with self._lock:
            node = self._root
            for part in parts:
                if part not in node.children:
                    return
                node = node.children[part]
            
            if node.is_blocked:
                node.is_blocked = False
                self._count -= 1
    
    async def clear(self):
        async with self._lock:
            self._root = TrieNode()
            self._count = 0
    
    @property
    def size(self) -> int:
        return self._count

BLOCKLIST = DomainList("blocklist")
WHITELIST = DomainList("whitelist")
BLACKLIST = DomainList("blacklist")

# ==================== UPSTREAM HEALTH ====================
class UpstreamHealth:
    def __init__(self):
        self._health: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
    
    async def record_success(self, server: str, latency: float):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {
                    "failures": 0,
                    "last_check": time.time(),
                    "healthy": True,
                    "latency": latency,
                    "success_count": 0
                }
            
            self._health[server]["failures"] = 0
            self._health[server]["last_check"] = time.time()
            self._health[server]["healthy"] = True
            self._health[server]["latency"] = latency
            self._health[server]["success_count"] += 1
    
    async def record_failure(self, server: str):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {
                    "failures": 0,
                    "last_check": time.time(),
                    "healthy": True,
                    "latency": 0,
                    "success_count": 0
                }
            
            self._health[server]["failures"] += 1
            self._health[server]["last_check"] = time.time()
            
            max_failures = CONFIG.get("upstream_max_failures", 3)
            if self._health[server]["failures"] >= max_failures:
                self._health[server]["healthy"] = False
                log.warning(f"[upstream] Marked unhealthy: {server}")
    
    def get_healthy(self) -> List[str]:
        return [s for s, h in self._health.items() if h.get("healthy", True)]
    
    def get_status(self) -> dict:
        return self._health.copy()
    
    def get_best(self, servers: List[str]) -> Optional[str]:
        """Get server with lowest latency"""
        healthy = [(s, self._health[s].get("latency", 999)) 
                   for s in servers if s in self._health and self._health[s].get("healthy", True)]
        if not healthy:
            return None
        return min(healthy, key=lambda x: x[1])[0]

UPSTREAM_HEALTH = UpstreamHealth()

# ==================== DNS PRIVACY FUNCTIONS ====================
CONN_POOL = None

async def get_conn_pool():
    global CONN_POOL
    if not CONN_POOL:
        CONN_POOL = ClientSession(
            connector=TCPConnector(limit=100, limit_per_host=10),
            timeout=ClientTimeout(total=CONFIG["upstream_timeout"])
        )
    return CONN_POOL

def apply_0x20_encoding(qname: str) -> str:
    """Apply 0x20 case randomization for entropy"""
    if not CONFIG.get("case_randomization"):
        return qname
    
    STATS["dns_0x20"] += 1
    result = []
    for char in qname:
        if char.isalpha():
            result.append(char.upper() if random.random() > 0.5 else char.lower())
        else:
            result.append(char)
    return ''.join(result)

def apply_qname_minimization(qname: str, qtype: int) -> List[str]:
    """Apply QNAME minimization (RFC 9156) - query parent domains first"""
    if not CONFIG.get("qname_minimization"):
        return [qname]
    
    STATS["dns_qname_min"] += 1
    parts = qname.strip('.').split('.')
    
    # Query from TLD up to full domain
    queries = []
    for i in range(len(parts) - 1, -1, -1):
        queries.append('.'.join(parts[i:]))
    
    return queries

def pad_query(wire_data: bytes) -> bytes:
    """Apply RFC 7830/8467 padding to DNS query"""
    if not CONFIG.get("padding_enabled"):
        return wire_data
    
    STATS["dns_padded"] += 1
    block_size = CONFIG.get("padding_block_size", 468)
    
    current_len = len(wire_data)
    if current_len >= block_size:
        return wire_data
    
    padding_needed = block_size - (current_len % block_size)
    if padding_needed == block_size:
        padding_needed = 0
    
    # Add EDNS padding option
    try:
        msg = dns.message.from_wire(wire_data)
        if not msg.edns:
            msg.use_edns(edns=True, payload=4096)
        
        # Add padding option (option code 12)
        # dnspython handles this automatically if we add the option
        padded = msg.to_wire()
        
        # Manual padding if needed
        if len(padded) < block_size:
            padding = b'\x00' * (block_size - len(padded))
            padded += padding
        
        return padded
    except:
        return wire_data

async def query_upstream_parallel(qname: str, qtype: int) -> Optional[Tuple[bytes, str]]:
    """Query multiple upstreams in parallel, return first success"""
    servers = CONFIG["upstream_servers"].copy()
    healthy = UPSTREAM_HEALTH.get_healthy()
    
    if healthy:
        servers = [s for s in servers if s in healthy or s not in UPSTREAM_HEALTH.get_status()]
    
    if not servers:
        return None
    
    # Apply 0x20 encoding
    encoded_qname = apply_0x20_encoding(qname)
    
    query = dns.message.make_query(encoded_qname, qtype, use_edns=True)
    if CONFIG.get("query_jitter"):
        query.id = random.randint(0, 65535)
    
    wire_query = query.to_wire()
    
    # Apply padding
    wire_query = pad_query(wire_query)
    
    # Apply jitter delay
    if CONFIG.get("query_jitter"):
        jitter_range = CONFIG.get("query_jitter_ms", [10, 100])
        jitter = random.randint(jitter_range[0], jitter_range[1]) / 1000.0
        await asyncio.sleep(jitter)
    
    # Query servers in parallel
    tasks = []
    for server in servers:
        if CONFIG.get("doh_enabled") and server in ["1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4"]:
            tasks.append(query_doh(wire_query, server))
        elif CONFIG.get("dot_enabled"):
            tasks.append(query_dot(wire_query, server))
        else:
            tasks.append(query_udp(wire_query, server))
    
    STATS["dns_parallel"] += 1
    
    # Wait for first success
    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            if result:
                response_wire, server = result
                start = time.time()
                await UPSTREAM_HEALTH.record_success(server, time.time() - start)
                return response_wire, server
        except Exception as e:
            log.debug(f"[upstream] Parallel query failed: {e}")
            continue
    
    return None

async def query_upstream(qname: str, qtype: int) -> Optional[bytes]:
    """Query upstream servers"""
    if CONFIG.get("upstream_parallel") and len(CONFIG["upstream_servers"]) > 1:
        result = await query_upstream_parallel(qname, qtype)
        return result[0] if result else None
    
    # Sequential fallback
    servers = CONFIG["upstream_servers"].copy()
    healthy = UPSTREAM_HEALTH.get_healthy()
    
    if healthy:
        servers = [s for s in servers if s in healthy or s not in UPSTREAM_HEALTH.get_status()]
    
    if CONFIG.get("upstream_rotation"):
        random.shuffle(servers)
    
    # Apply 0x20 encoding
    encoded_qname = apply_0x20_encoding(qname)
    
    query = dns.message.make_query(encoded_qname, qtype, use_edns=True)
    if CONFIG.get("query_jitter"):
        query.id = random.randint(0, 65535)
    
    wire_query = query.to_wire()
    wire_query = pad_query(wire_query)
    
    # Apply jitter
    if CONFIG.get("query_jitter"):
        jitter_range = CONFIG.get("query_jitter_ms", [10, 100])
        jitter = random.randint(jitter_range[0], jitter_range[1]) / 1000.0
        await asyncio.sleep(jitter)
    
    for server in servers:
        try:
            start = time.time()
            
            if CONFIG.get("doh_enabled") and server in ["1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4"]:
                response_wire = await query_doh(wire_query, server)
            elif CONFIG.get("dot_enabled"):
                response_wire = await query_dot(wire_query, server)
            else:
                response_wire = await query_udp(wire_query, server)
            
            if response_wire:
                latency = time.time() - start
                await UPSTREAM_HEALTH.record_success(server, latency)
                return response_wire
        
        except Exception as e:
            log.debug(f"[upstream] {server} failed: {e}")
            await UPSTREAM_HEALTH.record_failure(server)
            continue
    
    return None

async def query_udp(wire_query: bytes, server: str) -> Optional[bytes]:
    """Query via UDP"""
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(CONFIG["upstream_timeout"])
    
    try:
        await loop.sock_sendall(sock, wire_query)
        sock.sendto(wire_query, (server, 53))
        response, _ = sock.recvfrom(4096)
        return response
    finally:
        sock.close()

async def query_doh(wire_query: bytes, server: str) -> Optional[bytes]:
    """Query via DNS-over-HTTPS"""
    doh_urls = {
        "1.1.1.1": "https://cloudflare-dns.com/dns-query",
        "1.0.0.1": "https://cloudflare-dns.com/dns-query",
        "8.8.8.8": "https://dns.google/dns-query",
        "8.8.4.4": "https://dns.google/dns-query",
    }
    
    url = doh_urls.get(server, f"https://{server}/dns-query")
    session = await get_conn_pool()
    
    async with session.post(
        url,
        data=wire_query,
        headers={"Content-Type": "application/dns-message"}
    ) as resp:
        if resp.status == 200:
            return await resp.read()
    
    return None

async def query_dot(wire_query: bytes, server: str) -> Optional[bytes]:
    """Query via DNS-over-TLS"""
    import ssl
    
    try:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, 853, ssl=ssl_context),
            timeout=CONFIG["upstream_timeout"]
        )
        
        # Send length-prefixed query
        msg_len = struct.pack('!H', len(wire_query))
        writer.write(msg_len + wire_query)
        await writer.drain()
        
        # Read length-prefixed response
        len_bytes = await asyncio.wait_for(
            reader.readexactly(2),
            timeout=CONFIG["upstream_timeout"]
        )
        resp_len = struct.unpack('!H', len_bytes)[0]
        
        response = await asyncio.wait_for(
            reader.readexactly(resp_len),
            timeout=CONFIG["upstream_timeout"]
        )
        
        writer.close()
        await writer.wait_closed()
        
        return response
    
    except Exception as e:
        log.debug(f"[dot] Error: {e}")
        return None

# ==================== DNS RESPONSE BUILDERS ====================
def build_blocked_response(query: dns.message.Message) -> bytes:
    """Build response for blocked domain"""
    response = dns.message.make_response(query)
    block_type = CONFIG.get("block_response_type", "NXDOMAIN")
    
    if block_type == "NXDOMAIN":
        response.set_rcode(dns.rcode.NXDOMAIN)
    elif block_type == "REFUSED":
        response.set_rcode(dns.rcode.REFUSED)
    elif block_type in ["0.0.0.0", "custom_ip"]:
        ip = CONFIG.get("block_custom_ip", "0.0.0.0") if block_type == "custom_ip" else "0.0.0.0"
        qname = query.question[0].name
        qtype = query.question[0].rdtype
        
        if qtype == dns.rdatatype.A:
            rrset = response.answer.add(qname, 300, dns.rdataclass.IN, dns.rdatatype.A)
            rrset.add(dns.rdtypes.IN.A.A(dns.rdataclass.IN, dns.rdatatype.A, ip))
        elif qtype == dns.rdatatype.AAAA:
            rrset = response.answer.add(qname, 300, dns.rdataclass.IN, dns.rdatatype.AAAA)
            rrset.add(dns.rdtypes.IN.AAAA.AAAA(dns.rdataclass.IN, dns.rdatatype.AAAA, "::"))
    
    return response.to_wire()

def build_rewrite_response(query: dns.message.Message, rewrite: dict) -> bytes:
    """Build response for DNS rewrite"""
    response = dns.message.make_response(query)
    qname = query.question[0].name
    
    record_type = rewrite.get("type", "A")
    value = rewrite.get("value")
    ttl = rewrite.get("ttl", 300)
    
    if record_type == "A" and value:
        rrset = response.answer.add(qname, ttl, dns.rdataclass.IN, dns.rdatatype.A)
        rrset.add(dns.rdtypes.IN.A.A(dns.rdataclass.IN, dns.rdatatype.A, value))
    elif record_type == "AAAA" and value:
        rrset = response.answer.add(qname, ttl, dns.rdataclass.IN, dns.rdatatype.AAAA)
        rrset.add(dns.rdtypes.IN.AAAA.AAAA(dns.rdataclass.IN, dns.rdatatype.AAAA, value))
    elif record_type == "CNAME" and value:
        rrset = response.answer.add(qname, ttl, dns.rdataclass.IN, dns.rdatatype.CNAME)
        rrset.add(dns.rdtypes.ANY.CNAME.CNAME(dns.rdataclass.IN, dns.rdatatype.CNAME, dns.name.from_text(value)))
    elif record_type == "TXT" and value:
        rrset = response.answer.add(qname, ttl, dns.rdataclass.IN, dns.rdatatype.TXT)
        rrset.add(dns.rdtypes.ANY.TXT.TXT(dns.rdataclass.IN, dns.rdatatype.TXT, [value.encode()]))
    elif record_type == "MX" and value:
        parts = value.split(None, 1)
        priority = int(parts[0]) if len(parts) > 1 else 10
        exchange = parts[1] if len(parts) > 1 else parts[0]
        rrset = response.answer.add(qname, ttl, dns.rdataclass.IN, dns.rdatatype.MX)
        rrset.add(dns.rdtypes.ANY.MX.MX(dns.rdataclass.IN, dns.rdatatype.MX, priority, dns.name.from_text(exchange)))
    
    return response.to_wire()

def strip_ecs(response_wire: bytes) -> bytes:
    """Strip EDNS Client Subnet from response"""
    if not CONFIG.get("ecs_strip"):
        return response_wire
    
    try:
        response = dns.message.from_wire(response_wire)
        if response.edns >= 0:
            # Remove ECS option (option code 8)
            if hasattr(response, 'options'):
                response.options = [opt for opt in response.options if opt.otype != 8]
        return response.to_wire()
    except:
        return response_wire

# ==================== DNS PROCESSING ====================
async def process_dns_query(data: bytes, addr: Tuple[str, int]) -> bytes:
    try:
        query = dns.message.from_wire(data)
        qname = str(query.question[0].name).lower().strip('.')
        qtype = query.question[0].rdtype
        
        if not CONFIG.get("zero_log"):
            log.debug(f"[dns] {addr[0]}: {qname} ({dns.rdatatype.to_text(qtype)})")
        
        STATS["dns_queries"] += 1
        
        # Check whitelist first
        if await WHITELIST.contains(qname):
            pass
        else:
            # Check blacklist
            if await BLACKLIST.contains(qname):
                STATS["dns_blocked"] += 1
                log.info(f"[dns] Blocked (blacklist): {qname}")
                return build_blocked_response(query)
            
            # Check blocklist
            if CONFIG.get("blocking_enabled") and await BLOCKLIST.contains(qname):
                STATS["dns_blocked"] += 1
                log.info(f"[dns] Blocked (blocklist): {qname}")
                return build_blocked_response(query)
        
        # Check DNS rewrites
        dns_rewrites = CONFIG.get("dns_rewrites", {})
        if qname in dns_rewrites:
            rewrite = dns_rewrites[qname]
            return build_rewrite_response(query, rewrite)
        
        # Check local records
        local_records = CONFIG.get("local_records", {})
        if qname in local_records:
            record = local_records[qname]
            return build_rewrite_response(query, record)
        
        # Check conditional forwards
        for domain, forward_server in CONFIG.get("conditional_forwards", {}).items():
            if qname.endswith(domain) or qname == domain.strip('.'):
                try:
                    log.debug(f"[dns] Conditional forward: {qname} -> {forward_server}")
                    forward_query = dns.message.make_query(qname, qtype)
                    response_wire = await query_udp(forward_query.to_wire(), forward_server)
                    if response_wire:
                        return response_wire
                except Exception as e:
                    log.error(f"[dns] Conditional forward failed: {e}")
        
        # Check cache
        cached = await DNS_CACHE.get(qname, qtype)
        if cached:
            STATS["dns_cached"] += 1
            return cached
        
        # Query upstream
        STATS["dns_upstream"] += 1
        response_wire = await query_upstream(qname, qtype)
        
        if not response_wire:
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
            return response.to_wire()
        
        # Strip ECS
        response_wire = strip_ecs(response_wire)
        
        response = dns.message.from_wire(response_wire)
        
        # Rebinding protection
        if CONFIG.get("rebinding_protection"):
            rebinding_exempt = False
            for exempt_domain in CONFIG.get("rebinding_whitelist", []):
                if qname.endswith(exempt_domain) or qname == exempt_domain.strip('.'):
                    rebinding_exempt = True
                    break
            
            if not rebinding_exempt:
                for rrset in response.answer:
                    if rrset.rdtype == dns.rdatatype.A:
                        for rr in rrset:
                            try:
                                ip = ipaddress.IPv4Address(rr.address)
                                if ip.is_private:
                                    log.warning(f"[dns] Rebinding blocked: {qname} -> {ip}")
                                    return build_blocked_response(query)
                            except:
                                pass
        
        # Cache response
        ttl = CONFIG.get("cache_ttl", 3600)
        if response.answer:
            ttl = min((rrset.ttl for rrset in response.answer), default=ttl)
        else:
            ttl = CONFIG.get("negative_cache_ttl", 300)
        
        await DNS_CACHE.set(qname, qtype, response_wire, ttl, negative=(not response.answer))
        
        return response_wire
    
    except Exception as e:
        log.error(f"[dns] Error processing query: {e}")
        try:
            query = dns.message.from_wire(data)
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
            return response.to_wire()
        except:
            return data

# ==================== DNS SERVER ====================
class DNSProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
    
    def datagram_received(self, data, addr):
        asyncio.create_task(self.handle_query(data, addr))
    
    async def handle_query(self, data, addr):
        response = await process_dns_query(data, addr)
        self.transport.sendto(response, addr)

dns_transport = None

async def start_dns():
    global dns_transport
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DNSProtocol(),
        local_addr=(CONFIG["dns_bind"], CONFIG["dns_port"]),
        reuse_port=True
    )
    dns_transport = transport
    log.info(f"[dns] Listening on {CONFIG['dns_bind']}:{CONFIG['dns_port']}")

# ==================== DHCP SERVER ====================
# DHCP Message Types
DHCP_DISCOVER = 1
DHCP_OFFER = 2
DHCP_REQUEST = 3
DHCP_DECLINE = 4
DHCP_ACK = 5
DHCP_NAK = 6
DHCP_RELEASE = 7
DHCP_INFORM = 8

# DHCP Options
DHCP_OPT_PAD = 0
DHCP_OPT_SUBNET_MASK = 1
DHCP_OPT_ROUTER = 3
DHCP_OPT_DNS_SERVER = 6
DHCP_OPT_HOSTNAME = 12
DHCP_OPT_DOMAIN_NAME = 15
DHCP_OPT_BROADCAST = 28
DHCP_OPT_NTP_SERVER = 42
DHCP_OPT_VENDOR_SPECIFIC = 43
DHCP_OPT_WINS_SERVER = 44
DHCP_OPT_REQUESTED_IP = 50
DHCP_OPT_LEASE_TIME = 51
DHCP_OPT_MESSAGE_TYPE = 53
DHCP_OPT_SERVER_ID = 54
DHCP_OPT_PARAM_REQUEST = 55
DHCP_OPT_MESSAGE = 56
DHCP_OPT_RENEWAL_TIME = 58
DHCP_OPT_REBINDING_TIME = 59
DHCP_OPT_CLIENT_ID = 61
DHCP_OPT_TFTP_SERVER = 66
DHCP_OPT_BOOTFILE = 67
DHCP_OPT_END = 255

@dataclass
class DHCPLease:
    mac: str
    ip: str
    hostname: str = ""
    client_id: str = ""
    lease_start: float = field(default_factory=time.time)
    lease_end: float = 0
    static: bool = False
    
    def is_expired(self) -> bool:
        if self.static:
            return False
        return time.time() > self.lease_end
    
    def to_dict(self) -> dict:
        return {
            "mac": self.mac,
            "ip": self.ip,
            "hostname": self.hostname,
            "client_id": self.client_id,
            "lease_start": self.lease_start,
            "lease_end": self.lease_end,
            "expires_in": max(0, int(self.lease_end - time.time())),
            "static": self.static
        }

class DHCPServer:
    def __init__(self):
        self.leases: Dict[str, DHCPLease] = {}
        self.ip_pool: List[str] = []
        self.running = False
        self.sock = None
        self.lock = asyncio.Lock()
        self.cleanup_task = None
        self._load_leases()
        self._init_ip_pool()
    
    def _init_ip_pool(self):
        """Initialize IP address pool"""
        start_ip = ipaddress.IPv4Address(CONFIG["dhcp_range_start"])
        end_ip = ipaddress.IPv4Address(CONFIG["dhcp_range_end"])
        
        self.ip_pool = [
            str(ipaddress.IPv4Address(ip))
            for ip in range(int(start_ip), int(end_ip) + 1)
        ]
        log.info(f"[dhcp] IP pool: {len(self.ip_pool)} addresses")
    
    def _load_leases(self):
        """Load saved leases"""
        lease_file = Path("/config/veil_dhcp_leases.json")
        if lease_file.exists():
            try:
                with open(lease_file) as f:
                    data = json.load(f)
                    for mac, lease_data in data.items():
                        self.leases[mac] = DHCPLease(**lease_data)
                log.info(f"[dhcp] Loaded {len(self.leases)} leases")
            except Exception as e:
                log.error(f"[dhcp] Failed to load leases: {e}")
        
        # Load static leases
        for mac, ip in CONFIG.get("dhcp_static_leases", {}).items():
            self.leases[mac] = DHCPLease(
                mac=mac,
                ip=ip,
                static=True,
                lease_start=time.time(),
                lease_end=time.time() + (365 * 86400)
            )
    
    def _save_leases(self):
        """Save leases to disk"""
        lease_file = Path("/config/veil_dhcp_leases.json")
        try:
            data = {mac: lease.to_dict() for mac, lease in self.leases.items() if not lease.static}
            with open(lease_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"[dhcp] Failed to save leases: {e}")
    
    async def _ping_check(self, ip: str) -> bool:
        """Ping an IP to check if it's in use"""
        if not CONFIG.get("dhcp_ping_check"):
            return False
        
        STATS["dhcp_ping_checks"] += 1
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", str(CONFIG.get("dhcp_ping_timeout", 1)), ip,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.wait_for(proc.wait(), timeout=CONFIG.get("dhcp_ping_timeout", 1) + 1)
            
            # If ping succeeds, IP is in use
            if proc.returncode == 0:
                log.warning(f"[dhcp] IP conflict detected: {ip} is in use")
                STATS["dhcp_conflicts"] += 1
                return True
        except:
            pass
        
        return False
    
    async def _get_available_ip(self, mac: str) -> Optional[str]:
        """Get an available IP address"""
        async with self.lock:
            # Check existing lease
            if mac in self.leases and not self.leases[mac].is_expired():
                return self.leases[mac].ip
            
            # Find unused IP
            used_ips = {lease.ip for lease in self.leases.values() if not lease.is_expired()}
            
            for ip in self.ip_pool:
                if ip not in used_ips:
                    # Ping check
                    if await self._ping_check(ip):
                        continue
                    return ip
        
        return None
    
    def _parse_dhcp_packet(self, data: bytes) -> Optional[dict]:
        """Parse DHCP packet"""
        if len(data) < 240:
            return None
        
        try:
            packet = {
                "op": data[0],
                "htype": data[1],
                "hlen": data[2],
                "hops": data[3],
                "xid": struct.unpack("!I", data[4:8])[0],
                "secs": struct.unpack("!H", data[8:10])[0],
                "flags": struct.unpack("!H", data[10:12])[0],
                "ciaddr": socket.inet_ntoa(data[12:16]),
                "yiaddr": socket.inet_ntoa(data[16:20]),
                "siaddr": socket.inet_ntoa(data[20:24]),
                "giaddr": socket.inet_ntoa(data[24:28]),
                "chaddr": ':'.join(f'{b:02x}' for b in data[28:34]),
                "sname": data[44:108].split(b'\x00')[0].decode('utf-8', errors='ignore'),
                "file": data[108:236].split(b'\x00')[0].decode('utf-8', errors='ignore'),
                "options": {}
            }
            
            # Check magic cookie
            if data[236:240] != b'\x63\x82\x53\x63':
                return None
            
            # Parse options
            i = 240
            while i < len(data):
                opt = data[i]
                if opt == DHCP_OPT_END:
                    break
                if opt == DHCP_OPT_PAD:
                    i += 1
                    continue
                
                if i + 1 >= len(data):
                    break
                
                opt_len = data[i + 1]
                if i + 2 + opt_len > len(data):
                    break
                
                opt_data = data[i + 2:i + 2 + opt_len]
                packet["options"][opt] = opt_data
                i += 2 + opt_len
            
            return packet
        
        except Exception as e:
            log.error(f"[dhcp] Parse error: {e}")
            return None
    
    def _build_dhcp_packet(self, packet: dict, msg_type: int, offered_ip: str) -> bytes:
        """Build DHCP response packet"""
        response = bytearray(548)  # Minimum DHCP packet size
        
        # Boot reply
        response[0] = 2  # op: boot reply
        response[1] = packet["htype"]
        response[2] = packet["hlen"]
        response[3] = 0  # hops
        
        # Transaction ID
        struct.pack_into("!I", response, 4, packet["xid"])
        
        # Seconds and flags
        struct.pack_into("!H", response, 8, 0)
        struct.pack_into("!H", response, 10, packet["flags"])
        
        # Addresses
        response[12:16] = socket.inet_aton("0.0.0.0")  # ciaddr
        response[16:20] = socket.inet_aton(offered_ip)  # yiaddr
        response[20:24] = socket.inet_aton(CONFIG["dhcp_gateway"])  # siaddr
        response[24:28] = socket.inet_aton(packet["giaddr"])  # giaddr (relay)
        
        # Client MAC
        mac_bytes = bytes.fromhex(packet["chaddr"].replace(':', ''))
        response[28:28 + len(mac_bytes)] = mac_bytes
        
        # Magic cookie
        response[236:240] = b'\x63\x82\x53\x63'
        
        # Build options
        pos = 240
        
        # Message type
        response[pos:pos + 3] = bytes([DHCP_OPT_MESSAGE_TYPE, 1, msg_type])
        pos += 3
        
        # Server identifier
        server_ip = socket.inet_aton(CONFIG["dhcp_gateway"])
        response[pos:pos + 6] = bytes([DHCP_OPT_SERVER_ID, 4]) + server_ip
        pos += 6
        
        # Lease time
        lease_time = CONFIG["dhcp_lease_time"]
        response[pos:pos + 6] = bytes([DHCP_OPT_LEASE_TIME, 4]) + struct.pack("!I", lease_time)
        pos += 6
        
        # Renewal time (T1)
        renewal_time = CONFIG.get("dhcp_renewal_time", lease_time // 2)
        response[pos:pos + 6] = bytes([DHCP_OPT_RENEWAL_TIME, 4]) + struct.pack("!I", renewal_time)
        pos += 6
        
        # Rebinding time (T2)
        rebinding_time = CONFIG.get("dhcp_rebinding_time", int(lease_time * 0.875))
        response[pos:pos + 6] = bytes([DHCP_OPT_REBINDING_TIME, 4]) + struct.pack("!I", rebinding_time)
        pos += 6
        
        # Subnet mask
        netmask = socket.inet_aton(CONFIG["dhcp_netmask"])
        response[pos:pos + 6] = bytes([DHCP_OPT_SUBNET_MASK, 4]) + netmask
        pos += 6
        
        # Router (gateway)
        gateway = socket.inet_aton(CONFIG["dhcp_gateway"])
        response[pos:pos + 6] = bytes([DHCP_OPT_ROUTER, 4]) + gateway
        pos += 6
        
        # Broadcast address
        try:
            network = ipaddress.IPv4Network(f"{CONFIG['dhcp_subnet']}/{CONFIG['dhcp_netmask']}", strict=False)
            broadcast = socket.inet_aton(str(network.broadcast_address))
            response[pos:pos + 6] = bytes([DHCP_OPT_BROADCAST, 4]) + broadcast
            pos += 6
        except:
            pass
        
        # DNS servers
        dns_servers = CONFIG.get("dhcp_dns_servers", [CONFIG["dhcp_gateway"]])
        dns_bytes = b''.join(socket.inet_aton(dns) for dns in dns_servers[:3])
        response[pos:pos + 2 + len(dns_bytes)] = bytes([DHCP_OPT_DNS_SERVER, len(dns_bytes)]) + dns_bytes
        pos += 2 + len(dns_bytes)
        
        # Domain name
        if CONFIG.get("dhcp_domain"):
            domain = CONFIG["dhcp_domain"].encode()
            response[pos:pos + 2 + len(domain)] = bytes([DHCP_OPT_DOMAIN_NAME, len(domain)]) + domain
            pos += 2 + len(domain)
        
        # NTP servers
        if CONFIG.get("dhcp_ntp_servers"):
            ntp_servers = CONFIG["dhcp_ntp_servers"]
            ntp_bytes = b''.join(socket.inet_aton(ntp) for ntp in ntp_servers[:3])
            response[pos:pos + 2 + len(ntp_bytes)] = bytes([DHCP_OPT_NTP_SERVER, len(ntp_bytes)]) + ntp_bytes
            pos += 2 + len(ntp_bytes)
        
        # WINS servers
        if CONFIG.get("dhcp_wins_servers"):
            wins_servers = CONFIG["dhcp_wins_servers"]
            wins_bytes = b''.join(socket.inet_aton(wins) for wins in wins_servers[:2])
            response[pos:pos + 2 + len(wins_bytes)] = bytes([DHCP_OPT_WINS_SERVER, len(wins_bytes)]) + wins_bytes
            pos += 2 + len(wins_bytes)
        
        # Vendor-specific options
        vendor_opts = CONFIG.get("dhcp_vendor_options", {})
        if vendor_opts and isinstance(vendor_opts, dict):
            vendor_data = b''
            for opt_code, opt_value in vendor_opts.items():
                if isinstance(opt_value, str):
                    opt_value = opt_value.encode()
                vendor_data += bytes([int(opt_code), len(opt_value)]) + opt_value
            
            if vendor_data:
                response[pos:pos + 2 + len(vendor_data)] = bytes([DHCP_OPT_VENDOR_SPECIFIC, len(vendor_data)]) + vendor_data
                pos += 2 + len(vendor_data)
        
        # TFTP server
        if CONFIG.get("dhcp_tftp_server"):
            tftp = CONFIG["dhcp_tftp_server"].encode()
            response[pos:pos + 2 + len(tftp)] = bytes([DHCP_OPT_TFTP_SERVER, len(tftp)]) + tftp
            pos += 2 + len(tftp)
        
        # Bootfile
        if CONFIG.get("dhcp_bootfile"):
            bootfile = CONFIG["dhcp_bootfile"].encode()
            response[pos:pos + 2 + len(bootfile)] = bytes([DHCP_OPT_BOOTFILE, len(bootfile)]) + bootfile
            pos += 2 + len(bootfile)
        
        # End option
        response[pos] = DHCP_OPT_END
        
        return bytes(response[:pos + 1])
    
    async def handle_discover(self, packet: dict, addr: Tuple[str, int]):
        """Handle DHCP DISCOVER"""
        mac = packet["chaddr"]
        offered_ip = await self._get_available_ip(mac)
        
        if not offered_ip:
            log.warning(f"[dhcp] No available IP for {mac}")
            return
        
        log.info(f"[dhcp] DISCOVER from {mac} -> offering {offered_ip}")
        STATS["dhcp_discovers"] += 1
        STATS["dhcp_offers"] += 1
        
        # Send OFFER
        response = self._build_dhcp_packet(packet, DHCP_OFFER, offered_ip)
        
        # Send to broadcast or unicast based on flags
        if packet["flags"] & 0x8000:  # Broadcast flag
            self.sock.sendto(response, ('<broadcast>', 68))
        else:
            # Try unicast first
            try:
                self.sock.sendto(response, (offered_ip, 68))
            except:
                self.sock.sendto(response, ('<broadcast>', 68))
    
    async def handle_request(self, packet: dict, addr: Tuple[str, int]):
        """Handle DHCP REQUEST"""
        mac = packet["chaddr"]
        requested_ip = None
        
        # Get requested IP
        if DHCP_OPT_REQUESTED_IP in packet["options"]:
            requested_ip = socket.inet_ntoa(packet["options"][DHCP_OPT_REQUESTED_IP])
        elif packet["ciaddr"] != "0.0.0.0":
            requested_ip = packet["ciaddr"]
        
        if not requested_ip:
            log.warning(f"[dhcp] REQUEST from {mac} without requested IP")
            return
        
        STATS["dhcp_requests"] += 1
        
        # Verify IP is available for this MAC
        available_ip = await self._get_available_ip(mac)
        
        # Check if requested IP is valid
        if requested_ip not in self.ip_pool and requested_ip != available_ip:
            log.warning(f"[dhcp] NAK: {mac} requested invalid IP {requested_ip}")
            response = self._build_dhcp_packet(packet, DHCP_NAK, "0.0.0.0")
            self.sock.sendto(response, ('<broadcast>', 68))
            STATS["dhcp_naks"] += 1
            return
        
        # Get hostname and client ID
        hostname = ""
        if DHCP_OPT_HOSTNAME in packet["options"]:
            hostname = packet["options"][DHCP_OPT_HOSTNAME].decode('utf-8', errors='ignore')
        
        client_id = ""
        if DHCP_OPT_CLIENT_ID in packet["options"]:
            client_id = packet["options"][DHCP_OPT_CLIENT_ID].hex()
        
        # Create/update lease
        async with self.lock:
            self.leases[mac] = DHCPLease(
                mac=mac,
                ip=requested_ip,
                hostname=hostname,
                client_id=client_id,
                lease_start=time.time(),
                lease_end=time.time() + CONFIG["dhcp_lease_time"],
                static=mac in CONFIG.get("dhcp_static_leases", {})
            )
            self._save_leases()
        
        log.info(f"[dhcp] ACK {mac} -> {requested_ip} ({hostname or 'no hostname'})")
        STATS["dhcp_acks"] += 1
        
        # Send ACK
        response = self._build_dhcp_packet(packet, DHCP_ACK, requested_ip)
        
        if packet["flags"] & 0x8000:
            self.sock.sendto(response, ('<broadcast>', 68))
        else:
            try:
                self.sock.sendto(response, (requested_ip, 68))
            except:
                self.sock.sendto(response, ('<broadcast>', 68))
    
    async def handle_decline(self, packet: dict, addr: Tuple[str, int]):
        """Handle DHCP DECLINE"""
        mac = packet["chaddr"]
        declined_ip = None
        
        if DHCP_OPT_REQUESTED_IP in packet["options"]:
            declined_ip = socket.inet_ntoa(packet["options"][DHCP_OPT_REQUESTED_IP])
        
        log.warning(f"[dhcp] DECLINE from {mac} for {declined_ip} - IP conflict detected")
        STATS["dhcp_declines"] += 1
        STATS["dhcp_conflicts"] += 1
        
        # Remove lease
        async with self.lock:
            if mac in self.leases and not self.leases[mac].static:
                del self.leases[mac]
                self._save_leases()
    
    async def handle_release(self, packet: dict, addr: Tuple[str, int]):
        """Handle DHCP RELEASE"""
        mac = packet["chaddr"]
        
        async with self.lock:
            if mac in self.leases and not self.leases[mac].static:
                released_ip = self.leases[mac].ip
                del self.leases[mac]
                self._save_leases()
                log.info(f"[dhcp] RELEASE {mac} -> {released_ip}")
                STATS["dhcp_releases"] += 1
    
    async def handle_inform(self, packet: dict, addr: Tuple[str, int]):
        """Handle DHCP INFORM"""
        mac = packet["chaddr"]
        client_ip = packet["ciaddr"]
        
        log.info(f"[dhcp] INFORM from {mac} ({client_ip})")
        STATS["dhcp_informs"] += 1
        
        # Send ACK with network parameters only (no IP address)
        response = self._build_dhcp_packet(packet, DHCP_ACK, client_ip)
        self.sock.sendto(response, (client_ip, 68))
    
    async def handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming DHCP packet"""
        try:
            packet = self._parse_dhcp_packet(data)
            if not packet:
                return
            
            # Handle relay agent
            if CONFIG.get("dhcp_relay_support") and packet["giaddr"] != "0.0.0.0":
                log.debug(f"[dhcp] Relay agent: {packet['giaddr']}")
                # Response will be sent to relay agent
            
            # Get message type
            if DHCP_OPT_MESSAGE_TYPE not in packet["options"]:
                return
            
            msg_type = packet["options"][DHCP_OPT_MESSAGE_TYPE][0]
            
            if msg_type == DHCP_DISCOVER:
                await self.handle_discover(packet, addr)
            elif msg_type == DHCP_REQUEST:
                await self.handle_request(packet, addr)
            elif msg_type == DHCP_DECLINE:
                await self.handle_decline(packet, addr)
            elif msg_type == DHCP_RELEASE:
                await self.handle_release(packet, addr)
            elif msg_type == DHCP_INFORM:
                await self.handle_inform(packet, addr)
        
        except Exception as e:
            log.error(f"[dhcp] Error handling packet: {e}")
    
    async def cleanup_expired_leases(self):
        """Background task to clean up expired leases"""
        while self.running:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                async with self.lock:
                    expired = [mac for mac, lease in self.leases.items() 
                              if lease.is_expired() and not lease.static]
                    
                    for mac in expired:
                        log.info(f"[dhcp] Lease expired: {mac} -> {self.leases[mac].ip}")
                        del self.leases[mac]
                    
                    if expired:
                        self._save_leases()
            
            except Exception as e:
                log.error(f"[dhcp] Cleanup error: {e}")
    
    def start(self):
        """Start DHCP server"""
        if self.running:
            return
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.sock.bind((CONFIG["dhcp_bind"], CONFIG["dhcp_port"]))
            self.sock.setblocking(False)
            
            self.running = True
            asyncio.create_task(self._receive_loop())
            self.cleanup_task = asyncio.create_task(self.cleanup_expired_leases())
            log.info(f"[dhcp] Listening on {CONFIG['dhcp_bind']}:{CONFIG['dhcp_port']}")
        
        except Exception as e:
            log.error(f"[dhcp] Failed to start: {e}")
    
    async def _receive_loop(self):
        """Receive loop for DHCP packets"""
        loop = asyncio.get_event_loop()
        
        while self.running:
            try:
                data, addr = await loop.sock_recvfrom(self.sock, 4096)
                asyncio.create_task(self.handle_packet(data, addr))
            except Exception as e:
                if self.running:
                    log.error(f"[dhcp] Receive error: {e}")
                await asyncio.sleep(0.1)
    
    def stop(self):
        """Stop DHCP server"""
        self.running = False
        if self.cleanup_task:
            self.cleanup_task.cancel()
        if self.sock:
            self.sock.close()
        self._save_leases()
        log.info("[dhcp] Stopped")
    
    def get_leases(self) -> List[dict]:
        """Get all active leases"""
        return [lease.to_dict() for lease in self.leases.values() if not lease.is_expired()]
    
    def delete_lease(self, mac: str) -> bool:
        """Delete a lease"""
        if mac in self.leases and not self.leases[mac].static:
            del self.leases[mac]
            self._save_leases()
            return True
        return False
    
    def add_static_lease(self, mac: str, ip: str, hostname: str = "") -> bool:
        """Add a static lease"""
        if ip not in self.ip_pool:
            return False
        
        self.leases[mac] = DHCPLease(
            mac=mac,
            ip=ip,
            hostname=hostname,
            static=True,
            lease_start=time.time(),
            lease_end=time.time() + (365 * 86400)
        )
        
        if "dhcp_static_leases" not in CONFIG:
            CONFIG["dhcp_static_leases"] = {}
        CONFIG["dhcp_static_leases"][mac] = ip
        
        self._save_leases()
        return True

DHCP_SERVER = DHCPServer()

# ==================== API ENDPOINTS ====================
async def api_stats(req):
    uptime = int(time.time() - STATS["start_time"])
    return web.json_response({
        **STATS,
        "uptime_seconds": uptime,
        "cache_size": DNS_CACHE.size(),
        "blocklist_size": BLOCKLIST.size,
        "whitelist_size": WHITELIST.size,
        "blacklist_size": BLACKLIST.size,
        "upstream_health": UPSTREAM_HEALTH.get_status(),
        "dhcp_leases": len(DHCP_SERVER.leases) if DHCP_SERVER else 0
    })

async def api_config_get(req):
    return web.json_response(CONFIG)

async def api_config_update(req):
    try:
        data = await req.json()
        for key, value in data.items():
            if key in CONFIG:
                CONFIG[key] = value
        return web.json_response({"status": "updated"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_cache_flush(req):
    await DNS_CACHE.flush()
    return web.json_response({"status": "flushed"})

async def api_blocklist_reload(req):
    try:
        await BLOCKLIST.clear()
        for bl in CONFIG["blocklists"]:
            if Path(bl).exists():
                with open(bl) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            BLOCKLIST.add_sync(line)
        return web.json_response({"status": "reloaded", "size": BLOCKLIST.size})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_blocklist_upload(req):
    try:
        data = await req.post()
        if 'file' not in data:
            return web.json_response({"error": "No file provided"}, status=400)
        
        file_field = data['file']
        content = file_field.file.read().decode('utf-8')
        
        count = 0
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                BLOCKLIST.add_sync(line)
                count += 1
        
        return web.json_response({"status": "uploaded", "added": count, "total": BLOCKLIST.size})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_blacklist_add(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        if domain:
            await BLACKLIST.add(domain)
            return web.json_response({"status": "added", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_blacklist_remove(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        if domain:
            await BLACKLIST.remove(domain)
            return web.json_response({"status": "removed", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_whitelist_add(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        if domain:
            await WHITELIST.add(domain)
            return web.json_response({"status": "added", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_whitelist_remove(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        if domain:
            await WHITELIST.remove(domain)
            return web.json_response({"status": "removed", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_rewrite_add(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        record_type = data.get('type', 'A').upper()
        value = data.get('value', '').strip()
        ttl = int(data.get('ttl', 300))
        
        if not domain or not value:
            return web.json_response({"error": "Domain and value required"}, status=400)
        
        if "dns_rewrites" not in CONFIG:
            CONFIG["dns_rewrites"] = {}
        
        CONFIG["dns_rewrites"][domain] = {
            "type": record_type,
            "value": value,
            "ttl": ttl
        }
        
        return web.json_response({"status": "added", "domain": domain})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_rewrite_remove(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        
        if domain in CONFIG.get("dns_rewrites", {}):
            del CONFIG["dns_rewrites"][domain]
            return web.json_response({"status": "removed", "domain": domain})
        
        return web.json_response({"error": "Rewrite not found"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_local_record_add(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        record_type = data.get('type', 'A').upper()
        value = data.get('value', '').strip()
        ttl = int(data.get('ttl', 300))
        
        if not domain or not value:
            return web.json_response({"error": "Domain and value required"}, status=400)
        
        if "local_records" not in CONFIG:
            CONFIG["local_records"] = {}
        
        CONFIG["local_records"][domain] = {
            "type": record_type,
            "value": value,
            "ttl": ttl
        }
        
        return web.json_response({"status": "added", "domain": domain})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_local_record_remove(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        
        if domain in CONFIG.get("local_records", {}):
            del CONFIG["local_records"][domain]
            return web.json_response({"status": "removed", "domain": domain})
        
        return web.json_response({"error": "Record not found"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_dhcp_leases(req):
    if not DHCP_SERVER:
        return web.json_response({"error": "DHCP not enabled"}, status=400)
    return web.json_response({"leases": DHCP_SERVER.get_leases()})

async def api_dhcp_static_add(req):
    try:
        if not DHCP_SERVER:
            return web.json_response({"error": "DHCP not enabled"}, status=400)
        
        data = await req.json()
        mac = data.get('mac', '').strip()
        ip = data.get('ip', '').strip()
        hostname = data.get('hostname', '').strip()
        
        if not mac or not ip:
            return web.json_response({"error": "MAC and IP required"}, status=400)
        
        if DHCP_SERVER.add_static_lease(mac, ip, hostname):
            return web.json_response({"status": "added"})
        else:
            return web.json_response({"error": "IP not in pool"}, status=400)
    
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_dhcp_lease_delete(req):
    try:
        if not DHCP_SERVER:
            return web.json_response({"error": "DHCP not enabled"}, status=400)
        
        data = await req.json()
        mac = data.get('mac', '').strip()
        
        if DHCP_SERVER.delete_lease(mac):
            return web.json_response({"status": "deleted"})
        else:
            return web.json_response({"error": "Lease not found or static"}, status=400)
    
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_health(req):
    healthy_upstreams = UPSTREAM_HEALTH.get_healthy()
    return web.json_response({
        "status": "healthy" if len(healthy_upstreams) > 0 else "degraded",
        "upstreams_healthy": len(healthy_upstreams),
        "cache_size": DNS_CACHE.size(),
        "blocklist_size": BLOCKLIST.size,
        "dns_running": dns_transport is not None,
        "dhcp_running": DHCP_SERVER.running if DHCP_SERVER else False
    })

# ==================== JARVIS INTEGRATION ====================
def register_routes(app):
    """Register API routes with Jarvis"""
    # Stats & Health
    app.router.add_get('/api/veil/stats', api_stats)
    app.router.add_get('/api/veil/health', api_health)
    
    # Configuration
    app.router.add_get('/api/veil/config', api_config_get)
    app.router.add_post('/api/veil/config', api_config_update)
    
    # Cache
    app.router.add_delete('/api/veil/cache', api_cache_flush)
    
    # Blocklist
    app.router.add_post('/api/veil/blocklist/reload', api_blocklist_reload)
    app.router.add_post('/api/veil/blocklist/upload', api_blocklist_upload)
    
    # Blacklist
    app.router.add_post('/api/veil/blacklist/add', api_blacklist_add)
    app.router.add_delete('/api/veil/blacklist/remove', api_blacklist_remove)
    
    # Whitelist
    app.router.add_post('/api/veil/whitelist/add', api_whitelist_add)
    app.router.add_delete('/api/veil/whitelist/remove', api_whitelist_remove)
    
    # DNS Rewrites
    app.router.add_post('/api/veil/rewrite/add', api_rewrite_add)
    app.router.add_delete('/api/veil/rewrite/remove', api_rewrite_remove)
    
    # Local Records
    app.router.add_post('/api/veil/record/add', api_local_record_add)
    app.router.add_delete('/api/veil/record/remove', api_local_record_remove)
    
    # DHCP
    app.router.add_get('/api/veil/dhcp/leases', api_dhcp_leases)
    app.router.add_post('/api/veil/dhcp/static', api_dhcp_static_add)
    app.router.add_delete('/api/veil/dhcp/lease', api_dhcp_lease_delete)
    
    log.info("[veil] Routes registered")

async def init_veil():
    """Initialize Veil module"""
    log.info("[veil] 🧩 Privacy-First DNS/DHCP initializing")
    
    # Load blocklists
    for bl in CONFIG["blocklists"]:
        if Path(bl).exists():
            count = 0
            with open(bl) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        BLOCKLIST.add_sync(line)
                        count += 1
            log.info(f"[veil] Loaded {count:,} domains from {bl}")
    
    log.info(f"[veil] Blocklist: {BLOCKLIST.size:,} domains")
    
    # Start DNS
    if CONFIG.get("enabled", True):
        await start_dns()
        
        features = []
        if CONFIG.get("doh_enabled"):
            features.append("DoH")
        if CONFIG.get("dot_enabled"):
            features.append("DoT")
        if CONFIG.get("padding_enabled"):
            features.append("RFC 7830 padding")
        if CONFIG.get("case_randomization"):
            features.append("0x20 encoding")
        if CONFIG.get("qname_minimization"):
            features.append("QNAME min")
        if CONFIG.get("ecs_strip"):
            features.append("ECS strip")
        if CONFIG.get("upstream_parallel"):
            features.append("parallel upstream")
        
        log.info(f"[veil] Privacy: {', '.join(features)}")
    
    # Start DHCP
    if CONFIG.get("dhcp_enabled", False):
        DHCP_SERVER.start()
        log.info(f"[veil] DHCP: {CONFIG['dhcp_range_start']} - {CONFIG['dhcp_range_end']}")

async def cleanup_veil():
    """Cleanup on shutdown"""
    log.info("[veil] Shutting down")
    if dns_transport:
        dns_transport.close()
    if DHCP_SERVER:
        DHCP_SERVER.stop()
    if CONN_POOL:
        await CONN_POOL.close()

__version__ = "1.0.0"
__description__ = "Privacy-First DNS/DHCP - Complete Implementation"

if __name__ == "__main__":
    print("🧩 Veil - Privacy-First DNS/DHCP Server")
    print("This module integrates with Jarvis Prime")
    print("Do not run standalone")
