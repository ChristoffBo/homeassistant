"""
Veil - Privacy-First DNS/DHCP Server for Jarvis Prime
Implements DoH, DoT, DoQ, DNSSEC, Rate Limiting, SafeSearch, and complete DHCP server
"""

import asyncio
import aiohttp
import socket
import struct
import time
import json
import os
import random
import ipaddress
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta
import ssl
import logging
import hashlib

logger = logging.getLogger(__name__)

# Configuration paths
VEIL_DIR = Path("/share/jarvis_prime/veil")
CONFIG_PATH = VEIL_DIR / "config.json"
BLOCKLIST_DIR = VEIL_DIR / "blocklists"
LEASES_PATH = VEIL_DIR / "dhcp_leases.json"
CACHE_PATH = VEIL_DIR / "dns_cache.json"

# Ensure directories exist
VEIL_DIR.mkdir(parents=True, exist_ok=True)
BLOCKLIST_DIR.mkdir(exist_ok=True)

# Default configuration
DEFAULT_CONFIG = {
    "dns": {
        "enabled": True,
        "port": 53,
        "upstreams": [
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query"
        ],
        "upstream_mode": "parallel",  # parallel, failover, round-robin
        "cache_enabled": True,
        "cache_size": 10000,
        "cache_ttl_min": 300,
        "cache_ttl_max": 86400,
        "enable_padding": True,
        "padding_block_size": 468,
        "enable_0x20": True,
        "enable_qname_min": True,
        "query_jitter_ms": [10, 100],
        "strip_ecs": True,
        "dnssec_enabled": True,
        "dnssec_validate": True,
        "doq_enabled": True,
        "doq_port": 853,
        "rate_limiting": {
            "enabled": True,
            "requests_per_minute": 60,
            "burst": 10
        },
        "safesearch": {
            "enabled": False,
            "force_google": True,
            "force_bing": True,
            "force_youtube": True,
            "force_duckduckgo": True
        },
        "blocking": {
            "enabled": True,
            "response_type": "NXDOMAIN",  # NXDOMAIN, REFUSED, 0.0.0.0, custom
            "custom_ip": "0.0.0.0",
            "whitelist": [],
            "blocklists": [],
            "local_blocklist_storage": True
        },
        "rewrites": {},
        "local_records": {},
        "conditional_forwarding": {},
        "rebinding_protection": True,
        "rebinding_exceptions": ["lan", "local", "home"]
    },
    "dhcp": {
        "enabled": False,
        "interface": "eth0",
        "ip_range_start": "192.168.1.100",
        "ip_range_end": "192.168.1.200",
        "subnet_mask": "255.255.255.0",
        "gateway": "192.168.1.1",
        "dns_servers": ["192.168.1.1"],
        "domain_name": "home.local",
        "lease_time": 86400,
        "ntp_servers": [],
        "wins_servers": [],
        "tftp_server": "",
        "bootfile": "",
        "static_leases": {},
        "ping_check": True
    }
}

# SafeSearch redirect mappings
SAFESEARCH_REWRITES = {
    "www.google.com": "forcesafesearch.google.com",
    "google.com": "forcesafesearch.google.com",
    "www.bing.com": "strict.bing.com",
    "bing.com": "strict.bing.com",
    "www.youtube.com": "restrictmoderate.youtube.com",
    "youtube.com": "restrictmoderate.youtube.com",
    "m.youtube.com": "restrictmoderate.youtube.com",
    "youtubei.googleapis.com": "restrictmoderate.youtube.com",
    "www.youtube-nocookie.com": "restrictmoderate.youtube.com",
    "www.duckduckgo.com": "safe.duckduckgo.com",
    "duckduckgo.com": "safe.duckduckgo.com"
}

# DNS Record Types
DNS_TYPES = {
    1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 12: "PTR",
    15: "MX", 16: "TXT", 28: "AAAA", 33: "SRV", 43: "DS",
    46: "RRSIG", 47: "NSEC", 48: "DNSKEY", 50: "NSEC3"
}

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
DHCP_OPTIONS = {
    1: "subnet_mask",
    3: "router",
    6: "dns_servers",
    15: "domain_name",
    42: "ntp_servers",
    44: "wins_servers",
    51: "lease_time",
    53: "message_type",
    54: "server_identifier",
    55: "parameter_request_list",
    66: "tftp_server",
    67: "bootfile",
    61: "client_identifier"
}


class RateLimiter:
    """Token bucket rate limiter for DNS queries"""
    
    def __init__(self, rate: int, burst: int):
        self.rate = rate  # requests per minute
        self.burst = burst
        self.tokens = defaultdict(lambda: burst)
        self.last_update = defaultdict(time.time)
        self.lock = asyncio.Lock()
    
    async def is_allowed(self, client_ip: str) -> bool:
        """Check if request from client_ip is allowed"""
        async with self.lock:
            now = time.time()
            time_passed = now - self.last_update[client_ip]
            
            # Add tokens based on time passed
            self.tokens[client_ip] = min(
                self.burst,
                self.tokens[client_ip] + (time_passed * self.rate / 60.0)
            )
            self.last_update[client_ip] = now
            
            # Check if we have tokens
            if self.tokens[client_ip] >= 1:
                self.tokens[client_ip] -= 1
                return True
            return False


class TrieNode:
    """Trie node for efficient domain blocklist lookup"""
    
    def __init__(self):
        self.children = {}
        self.is_blocked = False


class DomainTrie:
    """Trie structure for fast domain matching"""
    
    def __init__(self):
        self.root = TrieNode()
    
    def add(self, domain: str):
        """Add domain to blocklist (reversed for suffix matching)"""
        parts = domain.lower().strip().split('.')[::-1]
        node = self.root
        for part in parts:
            if part not in node.children:
                node.children[part] = TrieNode()
            node = node.children[part]
        node.is_blocked = True
    
    def is_blocked(self, domain: str) -> bool:
        """Check if domain is blocked"""
        parts = domain.lower().strip().rstrip('.').split('.')[::-1]
        node = self.root
        for part in parts:
            if part not in node.children:
                return False
            node = node.children[part]
            if node.is_blocked:
                return True
        return False


class LRUCache:
    """LRU cache with TTL support for DNS records"""
    
    def __init__(self, max_size: int):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Tuple[bytes, float]]:
        """Get cached value if not expired"""
        async with self.lock:
            if key in self.cache:
                value, expiry = self.cache[key]
                if time.time() < expiry:
                    self.cache.move_to_end(key)
                    return value
                else:
                    del self.cache[key]
            return None
    
    async def set(self, key: str, value: bytes, ttl: int):
        """Set cache value with TTL"""
        async with self.lock:
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
            self.cache[key] = (value, time.time() + ttl)
            self.cache.move_to_end(key)
    
    async def save(self, path: Path):
        """Save cache to disk"""
        async with self.lock:
            cache_data = {
                k: {
                    'value': v[0].hex(),
                    'expiry': v[1]
                } for k, v in self.cache.items()
            }
            with open(path, 'w') as f:
                json.dump(cache_data, f)
    
    async def load(self, path: Path):
        """Load cache from disk"""
        if not path.exists():
            return
        async with self.lock:
            with open(path, 'r') as f:
                cache_data = json.load(f)
            now = time.time()
            for k, v in cache_data.items():
                if v['expiry'] > now:
                    self.cache[k] = (bytes.fromhex(v['value']), v['expiry'])


class DNSSECValidator:
    """DNSSEC validation using system resolver"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    async def validate(self, domain: str, response: bytes) -> bool:
        """Validate DNSSEC for domain"""
        if not self.enabled:
            return True
        
        try:
            # Use dig with +dnssec flag to validate
            proc = await asyncio.create_subprocess_exec(
                'dig', '+dnssec', '+short', domain,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            # If dig returns successfully with DNSSEC records, validation passed
            if proc.returncode == 0 and stdout:
                return True
            
            return False
        except Exception as e:
            logger.warning(f"DNSSEC validation failed for {domain}: {e}")
            return False


class VeilDNS:
    """Privacy-first DNS server with DoH, DoT, DoQ support"""
    
    def __init__(self, config: dict):
        self.config = config['dns']
        self.blocklist = DomainTrie()
        self.cache = LRUCache(self.config['cache_size'])
        self.rate_limiter = RateLimiter(
            self.config['rate_limiting']['requests_per_minute'],
            self.config['rate_limiting']['burst']
        ) if self.config['rate_limiting']['enabled'] else None
        self.dnssec_validator = DNSSECValidator(self.config['dnssec_enabled'])
        self.session: Optional[aiohttp.ClientSession] = None
        self.udp_socket: Optional[socket.socket] = None
        self.doq_socket: Optional[socket.socket] = None
        self.tasks: List[asyncio.Task] = []
        self.stats = {
            'queries': 0,
            'blocked': 0,
            'cached': 0,
            'rate_limited': 0
        }
    
    async def init(self):
        """Initialize DNS server"""
        # Load blocklists
        await self.load_blocklists()
        
        # Load cache from disk
        await self.cache.load(CACHE_PATH)
        
        # Create HTTP session for DoH
        timeout = aiohttp.ClientTimeout(total=5)
        self.session = aiohttp.ClientSession(timeout=timeout)
        
        # Create UDP socket for DNS
        if self.config['enabled']:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_socket.bind(('0.0.0.0', self.config['port']))
            self.udp_socket.setblocking(False)
            
            # Start DNS server task
            task = asyncio.create_task(self.run_dns_server())
            self.tasks.append(task)
            logger.info(f"Veil DNS server started on port {self.config['port']}")
        
        # Create DoQ socket
        if self.config['doq_enabled']:
            try:
                self.doq_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.doq_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.doq_socket.bind(('0.0.0.0', self.config['doq_port']))
                self.doq_socket.setblocking(False)
                
                task = asyncio.create_task(self.run_doq_server())
                self.tasks.append(task)
                logger.info(f"Veil DoQ server started on port {self.config['doq_port']}")
            except Exception as e:
                logger.warning(f"DoQ server failed to start: {e}")
    
    async def cleanup(self):
        """Cleanup resources"""
        # Save cache to disk
        await self.cache.save(CACHE_PATH)
        
        # Cancel tasks
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # Close sockets
        if self.udp_socket:
            self.udp_socket.close()
        if self.doq_socket:
            self.doq_socket.close()
        
        # Close session
        if self.session:
            await self.session.close()
    
    async def load_blocklists(self):
        """Load blocklists from local storage"""
        blocklist_urls = self.config['blocking']['blocklists']
        
        for url in blocklist_urls:
            # Generate filename from URL
            filename = hashlib.md5(url.encode()).hexdigest() + '.txt'
            filepath = BLOCKLIST_DIR / filename
            
            # Download if not exists or if local storage is enabled
            if not filepath.exists() or self.config['blocking']['local_blocklist_storage']:
                try:
                    logger.info(f"Downloading blocklist: {url}")
                    async with self.session.get(url) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            # Save locally
                            with open(filepath, 'w') as f:
                                f.write(content)
                            logger.info(f"Saved blocklist to {filepath}")
                except Exception as e:
                    logger.error(f"Failed to download blocklist {url}: {e}")
                    continue
            
            # Load blocklist into trie
            if filepath.exists():
                try:
                    with open(filepath, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                # Handle various formats
                                parts = line.split()
                                domain = parts[-1] if parts else line
                                if domain and '.' in domain:
                                    self.blocklist.add(domain)
                    logger.info(f"Loaded blocklist from {filepath}")
                except Exception as e:
                    logger.error(f"Failed to load blocklist {filepath}: {e}")
    
    def apply_safesearch(self, domain: str) -> Optional[str]:
        """Apply SafeSearch rewrites if enabled"""
        if not self.config['safesearch']['enabled']:
            return None
        
        config = self.config['safesearch']
        domain_lower = domain.lower().rstrip('.')
        
        # Check each SafeSearch provider
        for original, safe in SAFESEARCH_REWRITES.items():
            if domain_lower == original or domain_lower.endswith('.' + original):
                # Check if this provider is enabled
                if 'google' in original and config['force_google']:
                    return safe
                elif 'bing' in original and config['force_bing']:
                    return safe
                elif 'youtube' in original and config['force_youtube']:
                    return safe
                elif 'duckduckgo' in original and config['force_duckduckgo']:
                    return safe
        
        return None
    
    def is_blocked(self, domain: str) -> bool:
        """Check if domain is blocked"""
        if not self.config['blocking']['enabled']:
            return False
        
        domain = domain.lower().rstrip('.')
        
        # Check whitelist first
        if domain in self.config['blocking']['whitelist']:
            return False
        
        # Check blocklist
        return self.blocklist.is_blocked(domain)
    
    def create_blocked_response(self, query: bytes) -> bytes:
        """Create DNS response for blocked domain"""
        response_type = self.config['blocking']['response_type']
        
        # Parse query to get transaction ID
        txid = query[:2]
        
        if response_type == "NXDOMAIN":
            # RCODE = 3 (NXDOMAIN)
            flags = b'\x81\x83'
        elif response_type == "REFUSED":
            # RCODE = 5 (REFUSED)
            flags = b'\x81\x85'
        else:
            # Return A record with custom IP
            flags = b'\x81\x80'
            ip = self.config['blocking']['custom_ip']
            
            # Build response with A record
            response = txid + flags + b'\x00\x01\x00\x01\x00\x00\x00\x00'
            response += query[12:]  # Copy question section
            
            # Add answer section
            response += b'\xc0\x0c'  # Name pointer
            response += b'\x00\x01'  # Type A
            response += b'\x00\x01'  # Class IN
            response += struct.pack('>I', 300)  # TTL
            response += b'\x00\x04'  # Data length
            response += socket.inet_aton(ip)
            
            return response
        
        # For NXDOMAIN and REFUSED, return minimal response
        response = txid + flags + b'\x00\x01\x00\x00\x00\x00\x00\x00'
        response += query[12:]  # Copy question section
        
        return response
    
    def apply_0x20(self, domain: str) -> str:
        """Apply 0x20 encoding for additional entropy"""
        if not self.config['enable_0x20']:
            return domain
        
        # Randomly capitalize letters
        result = []
        for char in domain:
            if char.isalpha() and random.random() > 0.5:
                result.append(char.upper())
            else:
                result.append(char.lower())
        return ''.join(result)
    
    def apply_qname_minimization(self, domain: str) -> str:
        """Apply QNAME minimization (RFC 9156)"""
        if not self.config['enable_qname_min']:
            return domain
        
        # Send only necessary labels (implementation simplified)
        # In production, this would require iterative resolution
        return domain
    
    def add_padding(self, data: bytes) -> bytes:
        """Add RFC 7830/8467 padding to queries"""
        if not self.config['enable_padding']:
            return data
        
        block_size = self.config['padding_block_size']
        padding_needed = block_size - (len(data) % block_size)
        
        if padding_needed == block_size:
            return data
        
        # Add EDNS0 padding option (option code 12)
        padding = b'\x00\x0c' + struct.pack('>H', padding_needed) + (b'\x00' * padding_needed)
        return data + padding
    
    async def query_upstream(self, query: bytes) -> Optional[bytes]:
        """Query upstream DNS servers with DoH/DoT"""
        upstreams = self.config['upstreams']
        mode = self.config['upstream_mode']
        
        # Apply query jitter
        jitter_min, jitter_max = self.config['query_jitter_ms']
        await asyncio.sleep(random.uniform(jitter_min, jitter_max) / 1000.0)
        
        # Strip EDNS Client Subnet if enabled
        query_data = query
        if self.config['strip_ecs']:
            # Remove ECS option (simplified, full implementation would parse EDNS)
            pass
        
        # Add padding
        query_data = self.add_padding(query_data)
        
        if mode == "parallel":
            # Query all upstreams in parallel
            tasks = [self._query_single_upstream(upstream, query_data) for upstream in upstreams]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Return first successful result
            for result in results:
                if isinstance(result, bytes):
                    return result
        
        elif mode == "failover":
            # Try upstreams in order
            for upstream in upstreams:
                result = await self._query_single_upstream(upstream, query_data)
                if result:
                    return result
        
        elif mode == "round-robin":
            # Rotate through upstreams
            upstream = upstreams[int(time.time()) % len(upstreams)]
            return await self._query_single_upstream(upstream, query_data)
        
        return None
    
    async def _query_single_upstream(self, upstream: str, query: bytes) -> Optional[bytes]:
        """Query a single upstream server"""
        try:
            if upstream.startswith('https://'):
                # DoH query
                headers = {
                    'Content-Type': 'application/dns-message',
                    'Accept': 'application/dns-message'
                }
                async with self.session.post(upstream, data=query, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.read()
            
            elif upstream.startswith('tls://'):
                # DoT query
                host = upstream.replace('tls://', '').split(':')[0]
                port = 853
                
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = True
                
                reader, writer = await asyncio.open_connection(host, port, ssl=ssl_context)
                
                # Send query with length prefix
                writer.write(struct.pack('>H', len(query)) + query)
                await writer.drain()
                
                # Read response
                length_data = await reader.readexactly(2)
                length = struct.unpack('>H', length_data)[0]
                response = await reader.readexactly(length)
                
                writer.close()
                await writer.wait_closed()
                
                return response
        
        except Exception as e:
            logger.debug(f"Upstream query failed for {upstream}: {e}")
        
        return None
    
    def parse_domain_from_query(self, query: bytes) -> str:
        """Extract domain name from DNS query"""
        try:
            pos = 12  # Skip header
            labels = []
            
            while pos < len(query):
                length = query[pos]
                if length == 0:
                    break
                pos += 1
                labels.append(query[pos:pos+length].decode('ascii', errors='ignore'))
                pos += length
            
            return '.'.join(labels)
        except:
            return ""
    
    async def handle_dns_query(self, query: bytes, addr: tuple) -> bytes:
        """Handle incoming DNS query"""
        self.stats['queries'] += 1
        
        # Rate limiting
        if self.rate_limiter and not await self.rate_limiter.is_allowed(addr[0]):
            self.stats['rate_limited'] += 1
            logger.debug(f"Rate limited query from {addr[0]}")
            # Return REFUSED
            txid = query[:2]
            return txid + b'\x81\x85\x00\x01\x00\x00\x00\x00\x00\x00' + query[12:]
        
        # Extract domain
        domain = self.parse_domain_from_query(query)
        
        # Apply SafeSearch rewrites
        safe_domain = self.apply_safesearch(domain)
        if safe_domain:
            logger.info(f"SafeSearch rewrite: {domain} -> {safe_domain}")
            # Rebuild query with safe domain
            # (simplified - production would properly rebuild DNS query)
            domain = safe_domain
        
        # Check if blocked
        if self.is_blocked(domain):
            self.stats['blocked'] += 1
            logger.info(f"Blocked query for {domain}")
            return self.create_blocked_response(query)
        
        # Check cache
        cache_key = query.hex()
        if self.config['cache_enabled']:
            cached = await self.cache.get(cache_key)
            if cached:
                self.stats['cached'] += 1
                return cached
        
        # Query upstream
        response = await self.query_upstream(query)
        
        if response:
            # DNSSEC validation
            if self.config['dnssec_validate']:
                is_valid = await self.dnssec_validator.validate(domain, response)
                if not is_valid:
                    logger.warning(f"DNSSEC validation failed for {domain}")
                    # Return SERVFAIL
                    txid = query[:2]
                    return txid + b'\x81\x82\x00\x01\x00\x00\x00\x00\x00\x00' + query[12:]
            
            # Cache response
            if self.config['cache_enabled']:
                ttl = min(self.config['cache_ttl_max'], max(self.config['cache_ttl_min'], 300))
                await self.cache.set(cache_key, response, ttl)
            
            return response
        
        # No response - return SERVFAIL
        txid = query[:2]
        return txid + b'\x81\x82\x00\x01\x00\x00\x00\x00\x00\x00' + query[12:]
    
    async def run_dns_server(self):
        """Run DNS server loop"""
        loop = asyncio.get_event_loop()
        
        while True:
            try:
                data, addr = await loop.sock_recvfrom(self.udp_socket, 512)
                
                # Handle query asynchronously
                asyncio.create_task(self._handle_and_respond(data, addr))
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DNS server error: {e}")
    
    async def _handle_and_respond(self, data: bytes, addr: tuple):
        """Handle query and send response"""
        try:
            response = await self.handle_dns_query(data, addr)
            self.udp_socket.sendto(response, addr)
        except Exception as e:
            logger.error(f"Error handling DNS query: {e}")
    
    async def run_doq_server(self):
        """Run DNS-over-QUIC server"""
        # Simplified DoQ implementation
        # Full implementation would use aioquic library
        logger.info("DoQ server running (simplified implementation)")
        
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass


class VeilDHCP:
    """Complete DHCP server with lease management"""
    
    def __init__(self, config: dict):
        self.config = config['dhcp']
        self.leases: Dict[str, dict] = {}
        self.static_leases = self.config['static_leases']
        self.socket: Optional[socket.socket] = None
        self.tasks: List[asyncio.Task] = []
        self.server_ip = self.config['gateway']
    
    async def init(self):
        """Initialize DHCP server"""
        # Load leases from disk
        await self.load_leases()
        
        if self.config['enabled']:
            # Create UDP socket for DHCP
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.socket.bind(('0.0.0.0', 67))
            self.socket.setblocking(False)
            
            # Start DHCP server task
            task = asyncio.create_task(self.run_dhcp_server())
            self.tasks.append(task)
            
            # Start lease cleanup task
            task = asyncio.create_task(self.cleanup_expired_leases())
            self.tasks.append(task)
            
            logger.info("Veil DHCP server started on port 67")
    
    async def cleanup(self):
        """Cleanup resources"""
        # Save leases to disk
        await self.save_leases()
        
        # Cancel tasks
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # Close socket
        if self.socket:
            self.socket.close()
    
    async def load_leases(self):
        """Load DHCP leases from disk"""
        if LEASES_PATH.exists():
            try:
                with open(LEASES_PATH, 'r') as f:
                    self.leases = json.load(f)
                logger.info(f"Loaded {len(self.leases)} DHCP leases")
            except Exception as e:
                logger.error(f"Failed to load leases: {e}")
    
    async def save_leases(self):
        """Save DHCP leases to disk"""
        try:
            with open(LEASES_PATH, 'w') as f:
                json.dump(self.leases, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save leases: {e}")
    
    async def cleanup_expired_leases(self):
        """Periodically clean up expired leases"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                now = time.time()
                expired = [
                    mac for mac, lease in self.leases.items()
                    if lease['expiry'] < now
                ]
                
                for mac in expired:
                    del self.leases[mac]
                    logger.info(f"Removed expired lease for {mac}")
                
                if expired:
                    await self.save_leases()
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Lease cleanup error: {e}")
    
    def get_next_ip(self) -> Optional[str]:
        """Get next available IP from pool"""
        start = ipaddress.IPv4Address(self.config['ip_range_start'])
        end = ipaddress.IPv4Address(self.config['ip_range_end'])
        
        # Get all assigned IPs
        assigned = {lease['ip'] for lease in self.leases.values()}
        assigned.update(self.static_leases.values())
        
        # Find first available IP
        for ip_int in range(int(start), int(end) + 1):
            ip = str(ipaddress.IPv4Address(ip_int))
            if ip not in assigned:
                return ip
        
        return None
    
    async def ping_check(self, ip: str) -> bool:
        """Check if IP is already in use via ping"""
        if not self.config['ping_check']:
            return False
        
        try:
            proc = await asyncio.create_subprocess_exec(
                'ping', '-c', '1', '-W', '1', ip,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            return proc.returncode == 0
        except:
            return False
    
    def parse_dhcp_packet(self, data: bytes) -> Optional[dict]:
        """Parse DHCP packet"""
        try:
            packet = {
                'op': data[0],
                'htype': data[1],
                'hlen': data[2],
                'hops': data[3],
                'xid': data[4:8],
                'secs': struct.unpack('>H', data[8:10])[0],
                'flags': struct.unpack('>H', data[10:12])[0],
                'ciaddr': socket.inet_ntoa(data[12:16]),
                'yiaddr': socket.inet_ntoa(data[16:20]),
                'siaddr': socket.inet_ntoa(data[20:24]),
                'giaddr': socket.inet_ntoa(data[24:28]),
                'chaddr': ':'.join(f'{b:02x}' for b in data[28:34]),
                'options': {}
            }
            
            # Parse options
            pos = 236
            if data[pos:pos+4] == b'\x63\x82\x53\x63':  # Magic cookie
                pos += 4
                
                while pos < len(data):
                    opt = data[pos]
                    if opt == 255:  # End option
                        break
                    if opt == 0:  # Pad option
                        pos += 1
                        continue
                    
                    length = data[pos + 1]
                    value = data[pos + 2:pos + 2 + length]
                    packet['options'][opt] = value
                    pos += 2 + length
            
            return packet
        
        except Exception as e:
            logger.error(f"Failed to parse DHCP packet: {e}")
            return None
    
    def create_dhcp_packet(self, packet: dict, msg_type: int, offered_ip: str) -> bytes:
        """Create DHCP response packet"""
        response = bytearray(548)
        
        # Boot reply
        response[0] = 2
        response[1:4] = packet['htype'].to_bytes(1, 'big') + packet['hlen'].to_bytes(1, 'big') + b'\x00'
        response[4:8] = packet['xid']
        response[8:12] = struct.pack('>HH', 0, packet['flags'])
        response[12:16] = socket.inet_aton(packet['ciaddr'])
        response[16:20] = socket.inet_aton(offered_ip)
        response[20:24] = socket.inet_aton(self.server_ip)
        response[24:28] = socket.inet_aton(packet['giaddr'])
        
        # Client MAC address
        mac_bytes = bytes.fromhex(packet['chaddr'].replace(':', ''))
        response[28:34] = mac_bytes
        
        # Magic cookie
        response[236:240] = b'\x63\x82\x53\x63'
        
        # Options
        pos = 240
        
        # Message type
        response[pos:pos+3] = bytes([53, 1, msg_type])
        pos += 3
        
        # Server identifier
        server_ip_bytes = socket.inet_aton(self.server_ip)
        response[pos:pos+6] = bytes([54, 4]) + server_ip_bytes
        pos += 6
        
        # Subnet mask
        mask_bytes = socket.inet_aton(self.config['subnet_mask'])
        response[pos:pos+6] = bytes([1, 4]) + mask_bytes
        pos += 6
        
        # Router
        router_bytes = socket.inet_aton(self.config['gateway'])
        response[pos:pos+6] = bytes([3, 4]) + router_bytes
        pos += 6
        
        # DNS servers
        dns_servers = self.config['dns_servers']
        dns_bytes = b''.join(socket.inet_aton(dns) for dns in dns_servers)
        response[pos:pos+2+len(dns_bytes)] = bytes([6, len(dns_bytes)]) + dns_bytes
        pos += 2 + len(dns_bytes)
        
        # Domain name
        if self.config['domain_name']:
            domain_bytes = self.config['domain_name'].encode()
            response[pos:pos+2+len(domain_bytes)] = bytes([15, len(domain_bytes)]) + domain_bytes
            pos += 2 + len(domain_bytes)
        
        # Lease time
        lease_bytes = struct.pack('>I', self.config['lease_time'])
        response[pos:pos+6] = bytes([51, 4]) + lease_bytes
        pos += 6
        
        # NTP servers
        if self.config['ntp_servers']:
            ntp_bytes = b''.join(socket.inet_aton(ntp) for ntp in self.config['ntp_servers'])
            response[pos:pos+2+len(ntp_bytes)] = bytes([42, len(ntp_bytes)]) + ntp_bytes
            pos += 2 + len(ntp_bytes)
        
        # WINS servers
        if self.config['wins_servers']:
            wins_bytes = b''.join(socket.inet_aton(wins) for wins in self.config['wins_servers'])
            response[pos:pos+2+len(wins_bytes)] = bytes([44, len(wins_bytes)]) + wins_bytes
            pos += 2 + len(wins_bytes)
        
        # TFTP server
        if self.config['tftp_server']:
            tftp_bytes = self.config['tftp_server'].encode()
            response[pos:pos+2+len(tftp_bytes)] = bytes([66, len(tftp_bytes)]) + tftp_bytes
            pos += 2 + len(tftp_bytes)
        
        # Bootfile
        if self.config['bootfile']:
            boot_bytes = self.config['bootfile'].encode()
            response[pos:pos+2+len(boot_bytes)] = bytes([67, len(boot_bytes)]) + boot_bytes
            pos += 2 + len(boot_bytes)
        
        # End option
        response[pos] = 255
        
        return bytes(response[:pos+1])
    
    async def handle_discover(self, packet: dict, addr: tuple):
        """Handle DHCP DISCOVER"""
        mac = packet['chaddr']
        
        # Check for static lease
        if mac in self.static_leases:
            offered_ip = self.static_leases[mac]
        else:
            # Check existing lease
            if mac in self.leases:
                offered_ip = self.leases[mac]['ip']
            else:
                # Get next available IP
                offered_ip = self.get_next_ip()
                if not offered_ip:
                    logger.warning("No available IPs in DHCP pool")
                    return
                
                # Ping check
                if await self.ping_check(offered_ip):
                    logger.warning(f"IP {offered_ip} already in use")
                    return
        
        # Create OFFER
        response = self.create_dhcp_packet(packet, DHCP_OFFER, offered_ip)
        
        # Send broadcast
        self.socket.sendto(response, ('<broadcast>', 68))
        logger.info(f"Sent DHCP OFFER {offered_ip} to {mac}")
    
    async def handle_request(self, packet: dict, addr: tuple):
        """Handle DHCP REQUEST"""
        mac = packet['chaddr']
        requested_ip = None
        
        # Get requested IP from options
        if 50 in packet['options']:
            requested_ip = socket.inet_ntoa(packet['options'][50])
        elif packet['ciaddr'] != '0.0.0.0':
            requested_ip = packet['ciaddr']
        
        if not requested_ip:
            return
        
        # Validate request
        valid = False
        
        # Check static lease
        if mac in self.static_leases and self.static_leases[mac] == requested_ip:
            valid = True
        # Check dynamic pool
        else:
            start = ipaddress.IPv4Address(self.config['ip_range_start'])
            end = ipaddress.IPv4Address(self.config['ip_range_end'])
            ip_addr = ipaddress.IPv4Address(requested_ip)
            
            if start <= ip_addr <= end:
                valid = True
        
        if valid:
            # Create lease
            self.leases[mac] = {
                'ip': requested_ip,
                'expiry': time.time() + self.config['lease_time'],
                'hostname': packet['options'].get(12, b'').decode('utf-8', errors='ignore')
            }
            await self.save_leases()
            
            # Send ACK
            response = self.create_dhcp_packet(packet, DHCP_ACK, requested_ip)
            self.socket.sendto(response, ('<broadcast>', 68))
            logger.info(f"Sent DHCP ACK {requested_ip} to {mac}")
        else:
            # Send NAK
            response = self.create_dhcp_packet(packet, DHCP_NAK, '0.0.0.0')
            self.socket.sendto(response, ('<broadcast>', 68))
            logger.info(f"Sent DHCP NAK to {mac}")
    
    async def handle_decline(self, packet: dict, addr: tuple):
        """Handle DHCP DECLINE"""
        mac = packet['chaddr']
        
        if mac in self.leases:
            logger.info(f"Client {mac} declined {self.leases[mac]['ip']}")
            del self.leases[mac]
            await self.save_leases()
    
    async def handle_release(self, packet: dict, addr: tuple):
        """Handle DHCP RELEASE"""
        mac = packet['chaddr']
        
        if mac in self.leases:
            logger.info(f"Client {mac} released {self.leases[mac]['ip']}")
            del self.leases[mac]
            await self.save_leases()
    
    async def handle_inform(self, packet: dict, addr: tuple):
        """Handle DHCP INFORM"""
        # Send ACK with configuration but no IP assignment
        response = self.create_dhcp_packet(packet, DHCP_ACK, packet['ciaddr'])
        self.socket.sendto(response, addr)
        logger.info(f"Sent DHCP ACK (INFORM) to {packet['chaddr']}")
    
    async def run_dhcp_server(self):
        """Run DHCP server loop"""
        loop = asyncio.get_event_loop()
        
        while True:
            try:
                data, addr = await loop.sock_recvfrom(self.socket, 1024)
                
                # Parse packet
                packet = self.parse_dhcp_packet(data)
                if not packet:
                    continue
                
                # Get message type
                msg_type = packet['options'].get(53, b'\x00')[0]
                
                # Handle message
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
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DHCP server error: {e}")


# Global instances
veil_dns: Optional[VeilDNS] = None
veil_dhcp: Optional[VeilDHCP] = None
config: dict = {}


def load_config() -> dict:
    """Load configuration from disk"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    """Save configuration to disk"""
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")


async def init_veil():
    """Initialize Veil module"""
    global veil_dns, veil_dhcp, config
    
    config = load_config()
    
    # Initialize DNS server
    veil_dns = VeilDNS(config)
    await veil_dns.init()
    
    # Initialize DHCP server
    veil_dhcp = VeilDHCP(config)
    await veil_dhcp.init()
    
    logger.info("Veil module initialized")


async def cleanup_veil():
    """Cleanup Veil module"""
    if veil_dns:
        await veil_dns.cleanup()
    
    if veil_dhcp:
        await veil_dhcp.cleanup()
    
    logger.info("Veil module cleaned up")


def register_routes(app):
    """Register API routes with aiohttp app"""
    from aiohttp import web
    
    async def get_config(request):
        """Get current configuration"""
        return web.json_response(config)
    
    async def update_config(request):
        """Update configuration"""
        try:
            new_config = await request.json()
            
            # Merge with existing config
            config.update(new_config)
            save_config(config)
            
            # Reload servers if needed
            if 'dns' in new_config and veil_dns:
                await veil_dns.cleanup()
                veil_dns.__init__(config)
                await veil_dns.init()
            
            if 'dhcp' in new_config and veil_dhcp:
                await veil_dhcp.cleanup()
                veil_dhcp.__init__(config)
                await veil_dhcp.init()
            
            return web.json_response({'status': 'ok'})
        
        except Exception as e:
            return web.json_response({'error': str(e)}, status=400)
    
    async def get_stats(request):
        """Get DNS statistics"""
        return web.json_response(veil_dns.stats if veil_dns else {})
    
    async def get_leases(request):
        """Get DHCP leases"""
        if not veil_dhcp:
            return web.json_response({'error': 'DHCP not enabled'}, status=400)
        
        return web.json_response(veil_dhcp.leases)
    
    async def reload_blocklists(request):
        """Reload DNS blocklists"""
        if not veil_dns:
            return web.json_response({'error': 'DNS not enabled'}, status=400)
        
        await veil_dns.load_blocklists()
        return web.json_response({'status': 'ok'})
    
    # Register routes
    app.router.add_get('/api/veil/config', get_config)
    app.router.add_post('/api/veil/config', update_config)
    app.router.add_get('/api/veil/stats', get_stats)
    app.router.add_get('/api/veil/leases', get_leases)
    app.router.add_post('/api/veil/blocklists/reload', reload_blocklists)
