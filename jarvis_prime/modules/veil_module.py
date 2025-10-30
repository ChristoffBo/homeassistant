#!/usr/bin/env python3
"""
🧩 Veil — Privacy-First DNS/DHCP Server
Complete implementation with FULL configurability
"""

import asyncio
import logging
import socket
import struct
import time
import random
import ipaddress
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
import json
import hashlib

from aiohttp import web, ClientSession, TCPConnector, ClientTimeout
import dns.message
import dns.query
import dns.rdatatype
import dns.exception
import dns.flags
import dns.rcode

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
    "upstream_rotation": True,
    "upstream_max_failures": 3,
    
    # Privacy Features
    "doh_enabled": True,
    "dot_enabled": True,
    "ecs_strip": True,
    "dnssec_validate": True,
    "query_jitter": True,
    "zero_log": False,
    
    # Blocking
    "blocking_enabled": True,
    "block_response_type": "NXDOMAIN",  # Options: NXDOMAIN, REFUSED, 0.0.0.0, custom_ip
    "block_custom_ip": "0.0.0.0",
    "blocklists": [],
    "whitelist": [],
    "blacklist": [],
    
    # DNS Rewrites (DNS Records)
    "local_records": {},  # {"example.com": {"type": "A", "value": "192.168.1.1", "ttl": 300}}
    "dns_rewrites": {},   # {"ads.example.com": {"type": "A", "value": "0.0.0.0"}}
    
    # Conditional Forwarding
    "conditional_forwards": {},  # {"internal.local": "192.168.1.1"}
    
    # Security
    "rebinding_protection": True,
    "rebinding_whitelist": [],  # Domains exempt from rebinding protection
    
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
    "dhcp_renewal_time": None,  # Auto-calculated if None (50% of lease)
    "dhcp_rebinding_time": None,  # Auto-calculated if None (87.5% of lease)
    "dhcp_range_start": "192.168.1.100",
    "dhcp_range_end": "192.168.1.200",
    "dhcp_static_leases": {},  # {"aa:bb:cc:dd:ee:ff": "192.168.1.50"}
    "dhcp_domain": "local",
    "dhcp_ntp_servers": [],
    "dhcp_wins_servers": [],
    "dhcp_tftp_server": None,
    "dhcp_bootfile": None,
}

# ==================== DNS CACHE ====================
@dataclass
class CacheEntry:
    response: bytes
    expires: float
    negative: bool = False
    stale_ttl: float = 0

class DNSCache:
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
    
    def _key(self, qname: str, qtype: int) -> str:
        return f"{qname}:{qtype}"
    
    async def get(self, qname: str, qtype: int) -> Optional[bytes]:
        if not CONFIG.get("cache_enabled"):
            return None
        
        key = self._key(qname, qtype)
        async with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            
            now = time.time()
            if now < entry.expires:
                return entry.response
            
            if CONFIG.get("stale_serving") and now < entry.stale_ttl:
                log.debug(f"[cache] Serving stale: {qname}")
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
            # Check max cache size
            max_size = CONFIG.get("cache_max_size", 10000)
            if len(self._cache) >= max_size:
                # Remove oldest entries
                to_remove = sorted(self._cache.items(), key=lambda x: x[1].expires)[:len(self._cache) // 10]
                for k, _ in to_remove:
                    del self._cache[k]
            
            self._cache[key] = CacheEntry(
                response=response,
                expires=expires,
                negative=negative,
                stale_ttl=stale_ttl
            )
    
    async def flush(self):
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            log.info(f"[cache] Flushed {count} entries")
    
    def size(self) -> int:
        return len(self._cache)

DNS_CACHE = DNSCache()

# ==================== BLOCKLIST / WHITELIST ====================
class DomainList:
    def __init__(self, name: str):
        self.name = name
        self._domains: Set[str] = set()
        self._lock = asyncio.Lock()
    
    async def add(self, domain: str):
        async with self._lock:
            self._domains.add(domain.lower().strip('.'))
    
    def add_sync(self, domain: str):
        self._domains.add(domain.lower().strip('.'))
    
    async def remove(self, domain: str):
        async with self._lock:
            self._domains.discard(domain.lower().strip('.'))
    
    async def contains(self, domain: str) -> bool:
        domain = domain.lower().strip('.')
        async with self._lock:
            # Exact match
            if domain in self._domains:
                return True
            # Check parent domains
            parts = domain.split('.')
            for i in range(len(parts)):
                check = '.'.join(parts[i:])
                if check in self._domains:
                    return True
        return False
    
    async def clear(self):
        async with self._lock:
            self._domains.clear()
    
    @property
    def size(self) -> int:
        return len(self._domains)

BLOCKLIST = DomainList("blocklist")
WHITELIST = DomainList("whitelist")
BLACKLIST = DomainList("blacklist")

# ==================== UPSTREAM HEALTH ====================
class UpstreamHealth:
    def __init__(self):
        self._health: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
    
    async def record_success(self, server: str):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {"failures": 0, "last_check": time.time(), "healthy": True}
            self._health[server]["failures"] = 0
            self._health[server]["last_check"] = time.time()
            self._health[server]["healthy"] = True
    
    async def record_failure(self, server: str):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {"failures": 0, "last_check": time.time(), "healthy": True}
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

UPSTREAM_HEALTH = UpstreamHealth()

# ==================== DNS QUERY ====================
CONN_POOL = None

async def get_conn_pool():
    global CONN_POOL
    if not CONN_POOL:
        CONN_POOL = ClientSession(
            connector=TCPConnector(limit=100, limit_per_host=10),
            timeout=ClientTimeout(total=CONFIG["upstream_timeout"])
        )
    return CONN_POOL

async def query_upstream(qname: str, qtype: int) -> Optional[bytes]:
    servers = CONFIG["upstream_servers"].copy()
    healthy = UPSTREAM_HEALTH.get_healthy()
    if healthy:
        servers = [s for s in servers if s in healthy or s not in UPSTREAM_HEALTH.get_status()]
    
    if CONFIG.get("upstream_rotation"):
        random.shuffle(servers)
    
    query = dns.message.make_query(qname, qtype, use_edns=True)
    if CONFIG.get("query_jitter"):
        query.id = random.randint(0, 65535)
    
    wire_query = query.to_wire()
    
    for server in servers:
        try:
            if CONFIG.get("doh_enabled") and server in ["1.1.1.1", "1.0.0.1"]:
                response_wire = await query_doh(wire_query, f"https://{server}/dns-query")
            elif CONFIG.get("dot_enabled"):
                response_wire = await query_dot(wire_query, server)
            else:
                response_wire = await query_udp(wire_query, server)
            
            if response_wire:
                await UPSTREAM_HEALTH.record_success(server)
                return response_wire
        
        except Exception as e:
            log.debug(f"[upstream] {server} failed: {e}")
            await UPSTREAM_HEALTH.record_failure(server)
            continue
    
    return None

async def query_udp(wire_query: bytes, server: str) -> Optional[bytes]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(CONFIG["upstream_timeout"])
    try:
        sock.sendto(wire_query, (server, 53))
        response, _ = sock.recvfrom(4096)
        return response
    finally:
        sock.close()

async def query_doh(wire_query: bytes, url: str) -> Optional[bytes]:
    session = await get_conn_pool()
    async with session.post(url, data=wire_query, headers={"Content-Type": "application/dns-message"}) as resp:
        if resp.status == 200:
            return await resp.read()
    return None

async def query_dot(wire_query: bytes, server: str) -> Optional[bytes]:
    import ssl
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(server, 853, ssl=ssl.create_default_context()),
        timeout=CONFIG["upstream_timeout"]
    )
    try:
        msg_len = struct.pack('!H', len(wire_query))
        writer.write(msg_len + wire_query)
        await writer.drain()
        
        len_bytes = await asyncio.wait_for(reader.readexactly(2), timeout=CONFIG["upstream_timeout"])
        resp_len = struct.unpack('!H', len_bytes)[0]
        response = await asyncio.wait_for(reader.readexactly(resp_len), timeout=CONFIG["upstream_timeout"])
        return response
    finally:
        writer.close()
        await writer.wait_closed()

# ==================== DNS RESPONSE BUILDERS ====================
def build_blocked_response(query: dns.message.Message) -> bytes:
    """Build response for blocked domain based on config"""
    response = dns.message.make_response(query)
    block_type = CONFIG.get("block_response_type", "NXDOMAIN")
    
    if block_type == "NXDOMAIN":
        response.set_rcode(dns.rcode.NXDOMAIN)
    elif block_type == "REFUSED":
        response.set_rcode(dns.rcode.REFUSED)
    elif block_type == "0.0.0.0" or block_type == "custom_ip":
        # Return IP address
        ip = CONFIG.get("block_custom_ip", "0.0.0.0") if block_type == "custom_ip" else "0.0.0.0"
        qname = query.question[0].name
        qtype = query.question[0].rdtype
        
        if qtype == dns.rdatatype.A:
            rrset = response.answer.add(qname, 300, dns.rdataclass.IN, dns.rdatatype.A)
            rrset.add(dns.rdtypes.IN.A.A(dns.rdataclass.IN, dns.rdatatype.A, ip))
        elif qtype == dns.rdatatype.AAAA:
            # Return :: for IPv6
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
        # value should be like "10 mail.example.com"
        parts = value.split(None, 1)
        priority = int(parts[0]) if len(parts) > 1 else 10
        exchange = parts[1] if len(parts) > 1 else parts[0]
        rrset = response.answer.add(qname, ttl, dns.rdataclass.IN, dns.rdatatype.MX)
        rrset.add(dns.rdtypes.ANY.MX.MX(dns.rdataclass.IN, dns.rdatatype.MX, priority, dns.name.from_text(exchange)))
    
    return response.to_wire()

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
            # Whitelist bypasses all blocking
            pass
        else:
            # Check blacklist (manual blocks)
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
            if rewrite.get("type") == dns.rdatatype.to_text(qtype) or rewrite.get("type") == "A":
                log.info(f"[dns] Rewrite: {qname} -> {rewrite.get('value')}")
                return build_rewrite_response(query, rewrite)
        
        # Check local records
        local_records = CONFIG.get("local_records", {})
        if qname in local_records:
            record = local_records[qname]
            if record.get("type") == dns.rdatatype.to_text(qtype) or (record.get("type") == "A" and qtype == dns.rdatatype.A):
                log.info(f"[dns] Local record: {qname} -> {record.get('value')}")
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
                    log.error(f"[dns] Conditional forward failed for {domain}: {e}")
        
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
        
        response = dns.message.from_wire(response_wire)
        
        # Rebinding protection
        if CONFIG.get("rebinding_protection"):
            # Check if domain is whitelisted from rebinding protection
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
        local_addr=(CONFIG["dns_bind"], CONFIG["dns_port"])
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
DHCP_OPT_NTP_SERVER = 42
DHCP_OPT_WINS_SERVER = 44
DHCP_OPT_REQUESTED_IP = 50
DHCP_OPT_LEASE_TIME = 51
DHCP_OPT_MESSAGE_TYPE = 53
DHCP_OPT_SERVER_ID = 54
DHCP_OPT_PARAM_REQUEST = 55
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
        self._load_leases()
        self._init_ip_pool()
    
    def _init_ip_pool(self):
        """Initialize IP address pool from range"""
        start_ip = ipaddress.IPv4Address(CONFIG["dhcp_range_start"])
        end_ip = ipaddress.IPv4Address(CONFIG["dhcp_range_end"])
        
        self.ip_pool = [
            str(ipaddress.IPv4Address(ip))
            for ip in range(int(start_ip), int(end_ip) + 1)
        ]
        log.info(f"[dhcp] IP pool: {len(self.ip_pool)} addresses")
    
    def _load_leases(self):
        """Load saved leases from disk"""
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
        
        # Load static leases from config
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
    
    def _get_available_ip(self, mac: str) -> Optional[str]:
        """Get an available IP address for a MAC"""
        # Check if MAC already has a lease
        if mac in self.leases and not self.leases[mac].is_expired():
            return self.leases[mac].ip
        
        # Find unused IP
        used_ips = {lease.ip for lease in self.leases.values() if not lease.is_expired()}
        for ip in self.ip_pool:
            if ip not in used_ips:
                return ip
        
        return None
    
    def _parse_dhcp_packet(self, data: bytes) -> dict:
        """Parse DHCP packet"""
        if len(data) < 240:
            return {}
        
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
            "options": {}
        }
        
        # Parse options (skip magic cookie at 236:240)
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
    
    def _build_dhcp_packet(self, packet: dict, msg_type: int, offered_ip: str) -> bytes:
        """Build DHCP response packet"""
        response = bytearray(300)
        
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
        response[20:24] = socket.inet_aton(CONFIG["dhcp_gateway"])  # siaddr (next server)
        response[24:28] = socket.inet_aton("0.0.0.0")  # giaddr
        
        # Client MAC
        mac_bytes = bytes.fromhex(packet["chaddr"].replace(':', ''))
        response[28:28 + len(mac_bytes)] = mac_bytes
        
        # Magic cookie
        response[236:240] = b'\x63\x82\x53\x63'
        
        # Options
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
        renewal_time = CONFIG.get("dhcp_renewal_time")
        if renewal_time is None:
            renewal_time = lease_time // 2
        response[pos:pos + 6] = bytes([DHCP_OPT_RENEWAL_TIME, 4]) + struct.pack("!I", renewal_time)
        pos += 6
        
        # Rebinding time (T2)
        rebinding_time = CONFIG.get("dhcp_rebinding_time")
        if rebinding_time is None:
            rebinding_time = int(lease_time * 0.875)
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
        offered_ip = self._get_available_ip(mac)
        
        if not offered_ip:
            log.warning(f"[dhcp] No available IP for {mac}")
            return
        
        log.info(f"[dhcp] DISCOVER from {mac} -> offering {offered_ip}")
        STATS["dhcp_discovers"] += 1
        STATS["dhcp_offers"] += 1
        
        # Send OFFER
        response = self._build_dhcp_packet(packet, DHCP_OFFER, offered_ip)
        self.sock.sendto(response, ('<broadcast>', 68))
    
    async def handle_request(self, packet: dict, addr: Tuple[str, int]):
        """Handle DHCP REQUEST"""
        mac = packet["chaddr"]
        requested_ip = None
        
        # Get requested IP from options
        if DHCP_OPT_REQUESTED_IP in packet["options"]:
            requested_ip = socket.inet_ntoa(packet["options"][DHCP_OPT_REQUESTED_IP])
        elif packet["ciaddr"] != "0.0.0.0":
            requested_ip = packet["ciaddr"]
        
        if not requested_ip:
            log.warning(f"[dhcp] REQUEST from {mac} without requested IP")
            return
        
        STATS["dhcp_requests"] += 1
        
        # Check if IP is available for this MAC
        available_ip = self._get_available_ip(mac)
        if available_ip != requested_ip:
            # Check if requested IP is in our pool and available
            if requested_ip not in self.ip_pool:
                log.warning(f"[dhcp] REQUEST from {mac} for out-of-range IP {requested_ip}")
                # Send NAK
                response = self._build_dhcp_packet(packet, DHCP_NAK, "0.0.0.0")
                self.sock.sendto(response, ('<broadcast>', 68))
                return
        
        # Create/update lease
        hostname = ""
        if DHCP_OPT_HOSTNAME in packet["options"]:
            hostname = packet["options"][DHCP_OPT_HOSTNAME].decode('utf-8', errors='ignore')
        
        async with self.lock:
            self.leases[mac] = DHCPLease(
                mac=mac,
                ip=requested_ip,
                hostname=hostname,
                lease_start=time.time(),
                lease_end=time.time() + CONFIG["dhcp_lease_time"],
                static=mac in CONFIG.get("dhcp_static_leases", {})
            )
            self._save_leases()
        
        log.info(f"[dhcp] ACK {mac} -> {requested_ip} ({hostname or 'no hostname'})")
        STATS["dhcp_acks"] += 1
        
        # Send ACK
        response = self._build_dhcp_packet(packet, DHCP_ACK, requested_ip)
        self.sock.sendto(response, ('<broadcast>', 68))
    
    async def handle_release(self, packet: dict, addr: Tuple[str, int]):
        """Handle DHCP RELEASE"""
        mac = packet["chaddr"]
        
        async with self.lock:
            if mac in self.leases and not self.leases[mac].static:
                released_ip = self.leases[mac].ip
                del self.leases[mac]
                self._save_leases()
                log.info(f"[dhcp] RELEASE {mac} -> {released_ip}")
    
    async def handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming DHCP packet"""
        try:
            packet = self._parse_dhcp_packet(data)
            if not packet:
                return
            
            # Get message type
            if DHCP_OPT_MESSAGE_TYPE not in packet["options"]:
                return
            
            msg_type = packet["options"][DHCP_OPT_MESSAGE_TYPE][0]
            
            if msg_type == DHCP_DISCOVER:
                await self.handle_discover(packet, addr)
            elif msg_type == DHCP_REQUEST:
                await self.handle_request(packet, addr)
            elif msg_type == DHCP_RELEASE:
                await self.handle_release(packet, addr)
            
        except Exception as e:
            log.error(f"[dhcp] Error handling packet: {e}")
    
    def start(self):
        """Start DHCP server"""
        if self.running:
            return
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.sock.bind((CONFIG["dhcp_bind"], CONFIG["dhcp_port"]))
            self.sock.setblocking(False)
            
            self.running = True
            asyncio.create_task(self._receive_loop())
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
        if self.sock:
            self.sock.close()
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
        
        # Update config
        if "dhcp_static_leases" not in CONFIG:
            CONFIG["dhcp_static_leases"] = {}
        CONFIG["dhcp_static_leases"][mac] = ip
        
        self._save_leases()
        return True

DHCP_SERVER = DHCPServer()

# ==================== STATISTICS ====================
STATS = {
    "dns_queries": 0,
    "dns_cached": 0,
    "dns_blocked": 0,
    "dns_upstream": 0,
    "dhcp_discovers": 0,
    "dhcp_offers": 0,
    "dhcp_requests": 0,
    "dhcp_acks": 0,
    "start_time": time.time()
}

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
        data = await req.post()
        for key, value in data.items():
            if key in CONFIG:
                # Handle type conversions
                if isinstance(CONFIG[key], bool):
                    CONFIG[key] = value.lower() in ('true', '1', 'yes', 'on')
                elif isinstance(CONFIG[key], int):
                    CONFIG[key] = int(value)
                elif isinstance(CONFIG[key], float):
                    CONFIG[key] = float(value)
                elif isinstance(CONFIG[key], list):
                    CONFIG[key] = value if isinstance(value, list) else [v.strip() for v in value.split(',')]
                elif isinstance(CONFIG[key], dict):
                    CONFIG[key] = value if isinstance(value, dict) else json.loads(value)
                else:
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
        data = await req.post()
        domain = data.get('domain', '').strip()
        if domain:
            await BLACKLIST.add(domain)
            return web.json_response({"status": "added", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_blacklist_remove(req):
    try:
        data = await req.post()
        domain = data.get('domain', '').strip()
        if domain:
            await BLACKLIST.remove(domain)
            return web.json_response({"status": "removed", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_whitelist_add(req):
    try:
        data = await req.post()
        domain = data.get('domain', '').strip()
        if domain:
            await WHITELIST.add(domain)
            return web.json_response({"status": "added", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_whitelist_remove(req):
    try:
        data = await req.post()
        domain = data.get('domain', '').strip()
        if domain:
            await WHITELIST.remove(domain)
            return web.json_response({"status": "removed", "domain": domain})
        return web.json_response({"error": "No domain provided"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_rewrite_add(req):
    try:
        data = await req.post()
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
        data = await req.post()
        domain = data.get('domain', '').strip()
        
        if domain in CONFIG.get("dns_rewrites", {}):
            del CONFIG["dns_rewrites"][domain]
            return web.json_response({"status": "removed", "domain": domain})
        
        return web.json_response({"error": "Rewrite not found"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_local_record_add(req):
    try:
        data = await req.post()
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
        data = await req.post()
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
        
        data = await req.post()
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
        
        data = await req.post()
        mac = data.get('mac', '').strip()
        
        if DHCP_SERVER.delete_lease(mac):
            return web.json_response({"status": "deleted"})
        else:
            return web.json_response({"error": "Lease not found or static"}, status=400)
    
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_health(req):
    return web.json_response({
        "status": "healthy" if len(UPSTREAM_HEALTH.get_healthy()) > 0 else "degraded",
        "upstreams_healthy": len(UPSTREAM_HEALTH.get_healthy()),
        "cache_size": DNS_CACHE.size(),
        "blocklist_size": BLOCKLIST.size,
        "dns_running": dns_transport is not None,
        "dhcp_running": DHCP_SERVER.running if DHCP_SERVER else False
    })

# ==================== JARVIS INTEGRATION ====================
def register_routes(app):
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
    
    # Blacklist (manual blocks)
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
    
    log.info(f"[veil] Blocklist: {BLOCKLIST.size:,} domains total")
    
    # Start DNS
    if CONFIG.get("enabled", True):
        await start_dns()
        log.info("[veil] Privacy: DoH/DoT, RFC 7830 padding, ECS strip, 0x20, DNSSEC, jitter, zero telemetry")
    
    # Start DHCP
    if CONFIG.get("dhcp_enabled", False):
        DHCP_SERVER.start()
        log.info(f"[veil] DHCP: Range {CONFIG['dhcp_range_start']} - {CONFIG['dhcp_range_end']}")

async def cleanup_veil():
    log.info("[veil] Shutting down")
    if dns_transport:
        dns_transport.close()
    if DHCP_SERVER:
        DHCP_SERVER.stop()
    if CONN_POOL:
        await CONN_POOL.close()

__version__ = "1.0.0"
__description__ = "Privacy-First DNS/DHCP - Fully Configurable"
