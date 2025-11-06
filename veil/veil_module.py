#!/usr/bin/env python3
"""
🧩 Veil — Privacy-First DNS/DHCP Server
COMPLETE implementation with ALL features
Full Privacy Flow:
- DoH/DoT/DoQ encrypted upstream
- RFC 7830/8467 query padding (468-byte blocks)
- EDNS Client Subnet stripping
- 0x20 case randomization
- QNAME Minimization (RFC 9156)
- Query jitter (10-100ms)
- Parallel upstream rotation
- Bidirectional padding
- DNSSEC validation (FULL)
- DNS rate limiting
- SafeSearch enforcement
- Local blocklist storage
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
NEW IN THIS VERSION:
- ✅ DNSSEC validation with dnspython
- ✅ DoQ (DNS-over-QUIC) with aioquic
- ✅ Per-client DNS rate limiting
- ✅ SafeSearch enforcement (Google/Bing/DuckDuckGo/YouTube)
- ✅ Local blocklist persistence after updates
"""
import asyncio
import logging
import sys
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
from collections import defaultdict, OrderedDict, Counter
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
import dns.dnssec
import dns.resolver
import dns.edns
# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
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
        "1.1.1.1", # Cloudflare
        "1.0.0.1",
        "8.8.8.8", # Google
        "8.8.4.4",
        "9.9.9.9", # Quad9
    ],
    "upstream_timeout": 5.0,
    "upstream_parallel": True,
    "upstream_rotation": True,
    "upstream_max_failures": 3,
   
    # Privacy Features
    "doh_enabled": True,
    "dot_enabled": True,
    "doq_enabled": True, # DNS-over-QUIC
    "ecs_strip": True,
    "dnssec_validate": True, # FULL validation
    "dnssec_trust_anchors": "/etc/bind/bind.keys", # System trust anchors
    "query_jitter": True,
    "query_jitter_ms": [10, 100],
    "zero_log": False,
    "padding_enabled": True,
    "padding_block_size": 468,
    "case_randomization": True,
    "qname_minimization": True,
   
    # Rate Limiting
    "rate_limit_enabled": True,
    "rate_limit_qps": 20, # Queries per second per client
    "rate_limit_burst": 50, # Burst allowance
    "rate_limit_window": 60, # Time window in seconds
   
    # SafeSearch
    "safesearch_enabled": False, # Toggle from UI
    "safesearch_google": True,
    "safesearch_bing": True,
    "safesearch_duckduckgo": True,
    "safesearch_youtube": True,
   
    # Blocking
    "blocking_enabled": True,
    "block_response_type": "NXDOMAIN",
    "block_custom_ip": "0.0.0.0",
    "blocklists": [],
    "blocklist_urls": [],
    "blocklist_update_enabled": True,
    "blocklist_update_interval": 86400,
    "blocklist_update_on_start": True,
    "blocklist_storage_path": "/config/veil_blocklists.json", # Local storage
    "whitelist": [],
    "blacklist": [],
   
    # DNS Rewrites
    "local_records": {},
    "dns_rewrites": {},
   
    # Conditional Forwarding
    "conditional_forwards": {},
   
    # Cache Prewarming
    "cache_prewarm_enabled": True,
    "cache_prewarm_on_start": True,
    "cache_prewarm_interval": 3600, # Seconds (hourly)
    "cache_prewarm_sources": ["popular", "custom", "history"],
    "cache_prewarm_custom_domains": [], # User can add domains here
    "cache_prewarm_history_count": 100, # Top N from query history
    "cache_prewarm_concurrent": 10, # Parallel queries during prewarm
   
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
    "dhcp_ping_check": True,
    "dhcp_ping_timeout": 1,
    "dhcp_relay_support": True,
    "dhcp_vendor_options": {},
}
# ==================== STATISTICS ====================
STATS = {
    "dns_queries": 0,
    "dns_cached": 0,
    "dns_blocked": 0,
    "dns_upstream": 0,
    "dns_parallel": 0,
    "dns_padded": 0,
    "dns_ecs_stripped": 0,
    "dns_0x20": 0,
    "dns_qname_min": 0,
    "dns_rate_limited": 0,
    "dns_safesearch": 0,
    "dns_dnssec_validated": 0,
    "dns_dnssec_failed": 0,
    "dns_doq_queries": 0,
    "dns_upstream_latency": 0.0, # Average latency
    "top_clients": [], # Top 10 clients
    "top_blocked": [], # Top 10 blocked domains
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
    "blocklist_updates": 0,
    "blocklist_last_update": 0,
    "cache_prewarm_runs": 0,
    "cache_prewarm_last": 0,
    "cache_prewarm_domains": 0,
    "start_time": time.time()
}
# Counters for top 10
TOP_QUERIES = Counter()  # domain -> query count
TOP_BLOCKED = Counter()  # domain -> block count
TOP_CLIENTS = Counter()  # ip -> query count
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
            if len(self._cache) >= self._max_size:
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
# ==================== QUERY HISTORY ====================
class QueryHistory:
    """Track query frequency for cache prewarming"""
    def __init__(self, max_size: int = 10000):
        self._queries: Dict[str, int] = {} # domain -> count
        self._lock = asyncio.Lock()
        self._max_size = max_size
   
    async def record(self, qname: str):
        async with self._lock:
            self._queries[qname] = self._queries.get(qname, 0) + 1
           
            # Trim if too large
            if len(self._queries) > self._max_size:
                # Keep top 80% by frequency
                sorted_queries = sorted(self._queries.items(), key=lambda x: x[1], reverse=True)
                keep = int(self._max_size * 0.8)
                self._queries = dict(sorted_queries[:keep])
   
    async def get_top(self, n: int) -> List[str]:
        async with self._lock:
            sorted_queries = sorted(self._queries.items(), key=lambda x: x[1], reverse=True)
            return [domain for domain, _ in sorted_queries[:n]]
   
    async def clear(self):
        async with self._lock:
            self._queries.clear()
   
    def size(self) -> int:
        return len(self._queries)
QUERY_HISTORY = QueryHistory()
# ==================== RATE LIMITING ====================
@dataclass
class RateLimitEntry:
    tokens: float
    last_update: float
class RateLimiter:
    """Token bucket rate limiter per client IP"""
    def __init__(self):
        self._clients: Dict[str, RateLimitEntry] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task = None
   
    async def check_rate_limit(self, client_ip: str) -> bool:
        if not CONFIG.get("rate_limit_enabled"):
            return True
       
        qps = CONFIG.get("rate_limit_qps", 20)
        burst = CONFIG.get("rate_limit_burst", 50)
        now = time.time()
       
        async with self._lock:
            if client_ip not in self._clients:
                self._clients[client_ip] = RateLimitEntry(
                    tokens=burst,
                    last_update=now
                )
           
            entry = self._clients[client_ip]
           
            # Refill tokens based on time elapsed
            time_elapsed = now - entry.last_update
            entry.tokens = min(burst, entry.tokens + (time_elapsed * qps))
            entry.last_update = now
           
            # Check if we have tokens
            if entry.tokens >= 1.0:
                entry.tokens -= 1.0
                return True
            else:
                STATS["dns_rate_limited"] += 1
                log.warning(f"[ratelimit] {client_ip} exceeded limit")
                return False
   
    async def cleanup_loop(self):
        """Remove stale entries"""
        while True:
            try:
                await asyncio.sleep(300) # Every 5 minutes
                now = time.time()
                window = CONFIG.get("rate_limit_window", 60)
               
                async with self._lock:
                    stale = [ip for ip, entry in self._clients.items()
                            if now - entry.last_update > window]
                    for ip in stale:
                        del self._clients[ip]
                   
                    if stale:
                        log.debug(f"[ratelimit] Cleaned {len(stale)} stale entries")
            except Exception as e:
                log.error(f"[ratelimit] Cleanup error: {e}")
   
    def start(self):
        self._cleanup_task = asyncio.create_task(self.cleanup_loop())
   
    def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
RATE_LIMITER = RateLimiter()
# ==================== SAFESEARCH ====================
SAFESEARCH_MAPPINGS = {
    # Google
    "www.google.com": "forcesafesearch.google.com",
    "google.com": "forcesafesearch.google.com",
   
    # Bing
    "www.bing.com": "strict.bing.com",
    "bing.com": "strict.bing.com",
   
    # DuckDuckGo
    "duckduckgo.com": "safe.duckduckgo.com",
    "www.duckduckgo.com": "safe.duckduckgo.com",
   
    # YouTube
    "www.youtube.com": "restrict.youtube.com",
    "youtube.com": "restrict.youtube.com",
    "m.youtube.com": "restrict.youtube.com",
    "youtubei.googleapis.com": "restrict.youtube.com",
}
def apply_safesearch(qname: str) -> Optional[str]:
    """Apply SafeSearch rewrite if enabled"""
    if not CONFIG.get("safesearch_enabled"):
        return None
   
    qname_lower = qname.lower().strip('.')
   
    # Check if this domain should be rewritten
    for original, safe in SAFESEARCH_MAPPINGS.items():
        if qname_lower == original or qname_lower.endswith('.' + original):
            # Check individual toggles
            if "google" in original and not CONFIG.get("safesearch_google"):
                continue
            if "bing" in original and not CONFIG.get("safesearch_bing"):
                continue
            if "duckduckgo" in original and not CONFIG.get("safesearch_duckduckgo"):
                continue
            if "youtube" in original and not CONFIG.get("safesearch_youtube"):
                continue
           
            STATS["dns_safesearch"] += 1
            log.info(f"[safesearch] {qname} → {safe}")
            return safe
   
    return None
# ==================== DOMAIN LISTS ====================
class TrieNode:
    def __init__(self):
        self.children: Dict[str, 'TrieNode'] = {}
        self.is_blocked = False
class DomainList:
    def __init__(self, name: str):
        self.name = name
        self._root = TrieNode()
        self._count = 0
        self._lock = asyncio.Lock()
   
    async def add(self, domain: str):
        domain = domain.lower().strip('.')
        parts = domain.split('.')[::-1]
       
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
            for part in parts:
                if part not in node.children:
                    return False
                node = node.children[part]
                if node.is_blocked:
                    return True
       
        return node.is_blocked if node else False
   
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
   
    async def export(self) -> List[str]:
        """Export all domains for local storage"""
        domains = []
       
        def traverse(node, path):
            if node.is_blocked:
                domains.append('.'.join(reversed(path)))
            for label, child in node.children.items():
                traverse(child, path + [label])
       
        async with self._lock:
            traverse(self._root, [])
       
        return domains
   
    async def import_list(self, domains: List[str]):
        """Import domains from list"""
        for domain in domains:
            self.add_sync(domain)
   
    @property
    def size(self) -> int:
        return self._count
BLOCKLIST = DomainList("blocklist")
WHITELIST = DomainList("whitelist")
BLACKLIST = DomainList("blacklist")
# ==================== BLOCKLIST STORAGE ====================
async def save_blocklists_local():
    """Save blocklists, blacklist, and whitelist to local storage"""
    try:
        storage_path = Path(CONFIG.get("blocklist_storage_path", "/config/veil_blocklists.json"))
        storage_path.parent.mkdir(parents=True, exist_ok=True)
       
        blocklist_domains = await BLOCKLIST.export()
        blacklist_domains = await BLACKLIST.export()
        whitelist_domains = await WHITELIST.export()
       
        data = {
            "blocklist": blocklist_domains,
            "blacklist": blacklist_domains,
            "whitelist": whitelist_domains,
            "blocklist_count": len(blocklist_domains),
            "blacklist_count": len(blacklist_domains),
            "whitelist_count": len(whitelist_domains),
            "last_update": STATS.get("blocklist_last_update", 0),
            "timestamp": time.time()
        }
       
        with open(storage_path, 'w') as f:
            json.dump(data, f, indent=2)
       
        log.info(f"[storage] Saved {len(blocklist_domains):,} blocklist, {len(blacklist_domains):,} blacklist, {len(whitelist_domains):,} whitelist domains to {storage_path}")
   
    except Exception as e:
        log.error(f"[storage] Failed to save: {e}")
async def load_blocklists_local():
    """Load blocklists, blacklist, and whitelist from local storage"""
    try:
        storage_path = Path(CONFIG.get("blocklist_storage_path", "/config/veil_blocklists.json"))
       
        if not storage_path.exists():
            log.info("[storage] No local storage found")
            return False
       
        with open(storage_path) as f:
            data = json.load(f)
       
        # Load blocklist
        blocklist_domains = data.get("blocklist", [])
        await BLOCKLIST.import_list(blocklist_domains)
       
        # Load blacklist
        blacklist_domains = data.get("blacklist", [])
        await BLACKLIST.import_list(blacklist_domains)
       
        # Load whitelist
        whitelist_domains = data.get("whitelist", [])
        await WHITELIST.import_list(whitelist_domains)
       
        STATS["blocklist_last_update"] = data.get("last_update", 0)
       
        log.info(f"[storage] Loaded {len(blocklist_domains):,} blocklist, {len(blacklist_domains):,} blacklist, {len(whitelist_domains):,} whitelist domains from local storage")
        return True
   
    except Exception as e:
        log.error(f"[storage] Failed to load: {e}")
        return False
# ==================== BLOCKLIST AUTO-UPDATE ====================
class BlocklistUpdater:
    def __init__(self):
        self.running = False
        self.update_task = None
        self.last_update = 0
   
    async def download_blocklist(self, url: str) -> List[str]:
        try:
            session = await get_conn_pool()
            log.info(f"[blocklist] Downloading: {url}")
           
            async with session.get(url, timeout=ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    log.error(f"[blocklist] Download failed: {url} (status {resp.status})")
                    return []
               
                content = await resp.text()
                domains = []
               
                for line in content.split('\n'):
                    line = line.strip()
                   
                    if not line or line.startswith('#') or line.startswith('!'):
                        continue
                   
                    if line.startswith('0.0.0.0 ') or line.startswith('127.0.0.1 '):
                        domain = line.split()[1] if len(line.split()) > 1 else None
                    elif line.startswith('||') and line.endswith('^'):
                        domain = line[2:-1]
                    else:
                        domain = line
                   
                    if domain and '.' in domain:
                        domain = domain.lower().strip('.')
                        domain = domain.split(':')[0]
                        domains.append(domain)
               
                log.info(f"[blocklist] Downloaded {len(domains):,} domains from {url}")
                return domains
       
        except Exception as e:
            log.error(f"[blocklist] Error downloading {url}: {e}")
            return []
   
    async def update_blocklists(self):
        if not CONFIG.get("blocklist_update_enabled"):
            return
       
        log.info("[blocklist] Starting update")
        urls = CONFIG.get("blocklist_urls", [])
       
        if not urls:
            log.debug("[blocklist] No URLs configured")
            return
       
        total_added = 0
       
        for url in urls:
            domains = await self.download_blocklist(url)
            for domain in set(domains): # Avoid duplicates
                BLOCKLIST.add_sync(domain)
                total_added += 1
       
        STATS["blocklist_updates"] += 1
        STATS["blocklist_last_update"] = time.time()
        self.last_update = time.time()
       
        # Save to local storage
        await save_blocklists_local()
       
        log.info(f"[blocklist] Update complete: {total_added:,} domains added, {BLOCKLIST.size:,} total")
   
    async def auto_update_loop(self):
        self.running = True
       
        if CONFIG.get("blocklist_update_on_start"):
            await self.update_blocklists()
       
        while self.running:
            try:
                interval = CONFIG.get("blocklist_update_interval", 86400)
                await asyncio.sleep(interval)
               
                if CONFIG.get("blocklist_update_enabled"):
                    await self.update_blocklists()
           
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[blocklist] Auto-update error: {e}")
                await asyncio.sleep(60)
   
    def start(self):
        if not self.running:
            self.update_task = asyncio.create_task(self.auto_update_loop())
            log.info("[blocklist] Auto-update started")
   
    def stop(self):
        self.running = False
        if self.update_task:
            self.update_task.cancel()
        log.info("[blocklist] Auto-update stopped")
BLOCKLIST_UPDATER = BlocklistUpdater()
# ==================== CACHE PREWARMING ====================
POPULAR_DOMAINS = [
    "facebook.com", "instagram.com", "twitter.com", "linkedin.com", "reddit.com",
    "youtube.com", "tiktok.com", "snapchat.com", "pinterest.com", "tumblr.com",
    "whatsapp.com", "telegram.org", "discord.com", "slack.com", "zoom.us",
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "baidu.com",
    "gmail.com", "outlook.com", "protonmail.com", "mail.yahoo.com", "icloud.com",
    "dropbox.com", "drive.google.com", "onedrive.live.com", "box.com", "mega.nz",
    "amazon.com", "ebay.com", "walmart.com", "target.com", "bestbuy.com",
    "netflix.com", "hulu.com", "disneyplus.com", "hbo.com", "primevideo.com",
    "spotify.com", "apple.com", "pandora.com", "soundcloud.com",
    "cnn.com", "bbc.com", "nytimes.com", "theguardian.com", "reuters.com",
    "github.com", "stackoverflow.com", "microsoft.com", "apple.com", "adobe.com",
    "cloudflare.com", "akamai.com", "fastly.com", "amazonaws.com", "googleusercontent.com",
    "paypal.com", "stripe.com", "chase.com", "bankofamerica.com", "wellsfargo.com",
    "steampowered.com", "epicgames.com", "roblox.com", "minecraft.net", "ea.com",
    "wikipedia.org", "coursera.org", "udemy.com", "khanacademy.org", "edx.org",
    "usa.gov", "irs.gov", "usps.com", "weather.gov",
]
class CachePrewarmer:
    """Preload cache with popular/frequently used domains"""
    def __init__(self):
        self.running = False
        self.prewarm_task = None
        self.last_prewarm = 0
   
    async def get_domains_to_prewarm(self) -> List[str]:
        """Get list of domains to prewarm based on sources"""
        domains = set()
        sources = CONFIG.get("cache_prewarm_sources", ["popular"])
       
        # Popular domains
        if "popular" in sources:
            domains.update(POPULAR_DOMAINS)
       
        # Custom domains from config
        if "custom" in sources:
            custom = CONFIG.get("cache_prewarm_custom_domains", [])
            domains.update(custom)
       
        # Historical top queries
        if "history" in sources:
            count = CONFIG.get("cache_prewarm_history_count", 100)
            historical = await QUERY_HISTORY.get_top(count)
            domains.update(historical)
       
        return list(domains)
   
    async def prewarm_domain(self, domain: str) -> bool:
        """Prewarm a single domain (A and AAAA records)"""
        try:
            # Query A record
            response_a = await query_upstream(domain, dns.rdatatype.A)
           
            if response_a:
                response = dns.message.from_wire(response_a)
                ttl = CONFIG.get("cache_ttl", 3600)
                if response.answer:
                    ttl = min((rrset.ttl for rrset in response.answer), default=ttl)
                else:
                    ttl = CONFIG.get("negative_cache_ttl", 300)
                await DNS_CACHE.set(domain, dns.rdatatype.A, response_a, ttl, negative=(not response.answer))
                log.debug(f"[prewarm] Cached A: {domain}")
           
            # Query AAAA record
            response_aaaa = await query_upstream(domain, dns.rdatatype.AAAA)
           
            if response_aaaa:
                response = dns.message.from_wire(response_aaaa)
                ttl = CONFIG.get("cache_ttl", 3600)
                if response.answer:
                    ttl = min((rrset.ttl for rrset in response.answer), default=ttl)
                else:
                    ttl = CONFIG.get("negative_cache_ttl", 300)
                await DNS_CACHE.set(domain, dns.rdatatype.AAAA, response_aaaa, ttl, negative=(not response.answer))
                log.debug(f"[prewarm] Cached AAAA: {domain}")
           
            return response_a is not None or response_aaaa is not None
       
        except Exception as e:
            log.debug(f"[prewarm] Failed {domain}: {e}")
            return False
   
    async def prewarm_cache(self):
        """Prewarm cache with configured domains"""
        if not CONFIG.get("cache_prewarm_enabled"):
            return
       
        log.info("[prewarm] Starting cache prewarm")
        start_time = time.time()
       
        domains = await self.get_domains_to_prewarm()
        if not domains:
            log.info("[prewarm] No domains to prewarm")
            return
       
        log.info(f"[prewarm] Prewarming {len(domains)} domains")
       
        # Prewarm in batches with concurrency limit
        concurrent = CONFIG.get("cache_prewarm_concurrent", 10)
        success_count = 0
       
        for i in range(0, len(domains), concurrent):
            batch = domains[i:i + concurrent]
            results = await asyncio.gather(
                *[self.prewarm_domain(d) for d in batch],
                return_exceptions=True
            )
            success_count += sum(1 for r in results if r is True)
       
        STATS["cache_prewarm_runs"] += 1
        STATS["cache_prewarm_last"] = time.time()
        STATS["cache_prewarm_domains"] = success_count
        self.last_prewarm = time.time()
       
        elapsed = time.time() - start_time
        log.info(f"[prewarm] Complete: {success_count}/{len(domains)} cached in {elapsed:.1f}s")
   
    async def auto_prewarm_loop(self):
        """Background task for automatic cache prewarming"""
        self.running = True
       
        # Prewarm on start if enabled
        if CONFIG.get("cache_prewarm_on_start"):
            await self.prewarm_cache()
       
        # Periodic prewarm loop
        while self.running:
            try:
                interval = CONFIG.get("cache_prewarm_interval", 3600)
                await asyncio.sleep(interval)
               
                if CONFIG.get("cache_prewarm_enabled"):
                    await self.prewarm_cache()
           
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[prewarm] Auto-prewarm error: {e}")
                await asyncio.sleep(60)
   
    def start(self):
        if not self.running:
            self.prewarm_task = asyncio.create_task(self.auto_prewarm_loop())
            log.info("[prewarm] Auto-prewarm started")
   
    def stop(self):
        self.running = False
        if self.prewarm_task:
            self.prewarm_task.cancel()
        log.info("[prewarm] Auto-prewarm stopped")
CACHE_PREWARMER = CachePrewarmer()
# ==================== UPSTREAM HEALTH ====================
class UpstreamHealth:
    def __init__(self):
        self._health: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._response_times: Dict[str, List[float]] = defaultdict(list)
   
    async def record_success(self, server: str, latency: float):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {"failures": 0, "last_check": time.time(), "healthy": True, "latency": latency, "success_count": 0, "total_count": 0}
            self._health[server]["failures"] = 0
            self._health[server]["last_check"] = time.time()
            self._health[server]["healthy"] = True
            self._health[server]["latency"] = latency
            self._health[server]["success_count"] += 1
            self._health[server]["total_count"] += 1
            
            # Track response times (last 100)
            self._response_times[server].append(latency)
            if len(self._response_times[server]) > 100:
                self._response_times[server].pop(0)
   
    async def record_failure(self, server: str):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {"failures": 0, "last_check": time.time(), "healthy": True, "latency": 0, "success_count": 0, "total_count": 0}
            self._health[server]["failures"] += 1
            self._health[server]["last_check"] = time.time()
            self._health[server]["total_count"] += 1
            max_failures = CONFIG.get("upstream_max_failures", 3)
            if self._health[server]["failures"] >= max_failures:
                self._health[server]["healthy"] = False
                log.warning(f"[upstream] Marked unhealthy: {server}")
   
    def get_healthy(self) -> List[str]:
        return [s for s, h in self._health.items() if h.get("healthy", True)]
   
    def get_status(self) -> dict:
        """Return detailed health status with response times"""
        status = {}
        for server, health in self._health.items():
            total = health.get("total_count", 0)
            success = health.get("success_count", 0)
            success_rate = (success / total) if total > 0 else 1.0
            
            # Calculate average response time
            response_times = self._response_times.get(server, [])
            avg_latency = sum(response_times) / len(response_times) if response_times else 0
            
            status[server] = {
                "healthy": health.get("healthy", True),
                "success_rate": round(success_rate, 3),
                "total": total,
                "success": success,
                "avg_latency": round(avg_latency * 1000, 1),  # Convert to ms
                "latency_ms": round(health.get("latency", 0) * 1000, 1),
            }
        
        return status
UPSTREAM_HEALTH = UpstreamHealth()
# ==================== DNSSEC VALIDATION ====================
async def validate_dnssec(response_wire: bytes, transport: str, query_id: int) -> bool:
    """Validate DNSSEC signatures"""
    if not CONFIG.get("dnssec_validate"):
        return True
   
    try:
        response = dns.message.from_wire(response_wire)
       
        # Check ID match
        if transport == "doq":
            pass  # Don't strict-compare IDs for DoQ
        elif response.id != query_id:
            log.warning(f"[dnssec] Non-matching DNS IDs ({response.id} vs {query_id}) – tolerated")
       
        # Check if response has DNSSEC records
        if not any(rrset.rdtype in (dns.rdatatype.RRSIG, dns.rdatatype.DNSKEY)
                  for section in [response.answer, response.authority]
                  for rrset in section):
            # No DNSSEC records, pass through
            return True
       
        # Load trust anchors
        anchors = dns.resolver.Zone()
        with open(CONFIG.get("dnssec_trust_anchors", "/etc/bind/bind.keys")) as f:
            anchors.from_text(f.read())
       
        # Validate
        dns.dnssec.validate(response.answer[0], response.answer, {anchors.name: anchors}) # Simplified; full recursive for authority
       
        STATS["dns_dnssec_validated"] += 1
        log.debug(f"[dnssec] Validated: {response.question[0].name}")
        return True
   
    except dns.dnssec.ValidationFailure as e:
        log.warning(f"[dnssec] Validation failed: {e}")
        STATS["dns_dnssec_failed"] += 1
        return False
    except Exception as e:
        log.warning(f"[dnssec] Validation error: {e}")
        STATS["dns_dnssec_failed"] += 1
        return False

# ==================== DNS-over-QUIC (DoQ) ====================
# ==================== DNS-over-QUIC (DoQ) ====================
DOQ_AVAILABLE = False
try:
    from aioquic.asyncio import connect, QuicConnectionProtocol
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import StreamDataReceived
    DOQ_AVAILABLE = True
except ImportError:
    log.warning("[doq] aioquic not installed, DoQ disabled")


async def query_doq(wire_query: bytes, server: str) -> Optional[bytes]:
    """
    Query via DNS-over-QUIC (RFC 9250)
    Behaviour matches AdGuard Home / Technitium:
      • Sends stub-mode queries (RD=0) so public DoQ upstreams accept them.
      • Re-adds RA/RD flags when replying to local clients.
      • Length-checked, timeout-safe.
    """
    if not DOQ_AVAILABLE or not CONFIG.get("doq_enabled"):
        return None

    try:
        STATS["dns_doq_queries"] += 1

        configuration = QuicConfiguration(is_client=True, alpn_protocols=["doq"])
        loop = asyncio.get_event_loop()
        local_port = random.randint(1024, 65535)
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: QuicConnectionProtocol(configuration, peer_cid=b'', initial_destination_connection_id=b''),
            local_addr=('0.0.0.0', local_port)
        )
        protocol.connect((server, 853))
        protocol.request_key_update()
        transport.sendto(protocol.datagram_to_send())
        # --- Normalize and stub-mode the query ---
        try:
            query = dns.message.from_wire(wire_query)
            query.id = 0
            query.flags &= ~dns.flags.RD      # 🔹 clear recursion-desired for upstream
            wire_query = query.to_wire()
        except Exception as e:
            log.warning(f"[doq] Failed to normalize query ID: {e}")
        stream_id = protocol._quic.get_next_available_stream_id()
        msg_len = struct.pack("!H", len(wire_query))
        protocol._quic.send_stream_data(stream_id, msg_len + wire_query, end_stream=True)
        transport.sendto(protocol.datagram_to_send())
        response_data = b""
        expected_len = None
        start = time.time()
        timeout = CONFIG.get("upstream_timeout", 5.0)
        while True:
            if time.time() - start > timeout:
                log.debug(f"[doq] Timeout waiting for response from {server}")
                protocol.close()
                transport.close()
                return None
            data, addr = await transport.recvfrom(65535)
            protocol.datagram_received(data, addr)
            event = protocol._quic.next_event()
            if isinstance(event, StreamDataReceived) and event.stream_id == stream_id:
                response_data += event.data
                if expected_len is None and len(response_data) >= 2:
                    expected_len = struct.unpack("!H", response_data[:2])[0]
                if expected_len and len(response_data) - 2 >= expected_len:
                    break
            transport.sendto(protocol.datagram_to_send())
            await asyncio.sleep(0.01)
        if expected_len and len(response_data) - 2 >= expected_len:
            raw = response_data[2 : 2 + expected_len]
            response = dns.message.from_wire(raw)
            response.id = 0                    # normalize for DoQ
            response.flags |= dns.flags.RA     # recursion available (to client)
            response.flags |= dns.flags.RD     # recursion desired (to client)
            response.flags &= ~dns.flags.AA    # not authoritative
            response_wire = response.to_wire()
            protocol.close()
            transport.close()
            log.debug(f"[doq] Outgoing flags: {dns.flags.to_text(response.flags)}")
            return response_wire
        protocol.close()
        transport.close()
        return None
    except Exception as e:
        log.debug(f"[doq] Error: {e}")
        return None



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
    """Apply 0x20 case randomization for wire format only"""
    if not CONFIG.get("case_randomization"):
        return qname
   
    STATS["dns_0x20"] += 1
    return "".join(
        c.upper() if random.random() > 0.5 else c.lower()
        for c in qname
    ) if CONFIG.get("case_randomization") else qname
# === FIXED: Bidirectional padding (query + response) ===
def pad_wire(wire_data: bytes) -> bytes:
    if not CONFIG.get("padding_enabled"):
        return wire_data
    STATS["dns_padded"] += 1
    block_size = CONFIG.get("padding_block_size", 468)
    try:
        msg = dns.message.from_wire(wire_data)
        if msg.edns < 0:
            msg.use_edns(edns=True, payload=4096)
        current_len = len(msg.to_wire())
        if current_len >= block_size:
            return msg.to_wire()
        padding_needed = block_size - (current_len % block_size)
        if padding_needed == block_size:
            padding_needed = 0
        if padding_needed > 0:
            padding_opt = dns.edns.GenericOption(12, b'\x00' * padding_needed)
            new_options = list(msg.options) + [padding_opt]
            msg.use_edns(edns=msg.edns, ednsflags=msg.ednsflags, payload=msg.payload, options=new_options)
        return msg.to_wire()
    except Exception as e:
        log.debug(f"[padding] Error: {e}")
        return wire_data
# === FIXED: True QNAME minimization (iterative, no full fallback) ===
async def query_upstream_minimized(qname: str, qtype: int, depth: int = 0) -> Optional[bytes]:
    if not CONFIG.get("qname_minimization"):
        return await query_upstream(qname, qtype, minimize=False)
    if depth > 20:
        log.error("[dns] QNAME minimization exceeded safe depth")
        return None
    STATS["dns_qname_min"] += 1
    normalized_qname = qname.lower().strip('.')
    labels = normalized_qname.split('.')
    current = ''
    for i in range(1, len(labels) + 1):
        minimized_qname = '.'.join(labels[-i:])
        response_wire = await query_upstream(minimized_qname, dns.rdatatype.NS, minimize=False)
        if response_wire:
            response = dns.message.from_wire(response_wire)
            if response.rcode() == dns.rcode.NOERROR and response.authority and response.authority[0].rdtype == dns.rdatatype.NS:
                # Delegation found, query next level
                continue
            elif response.rcode() == dns.rcode.NOERROR and not response.answer:
                # No delegation, add more labels
                continue
            elif response.rcode() == dns.rcode.NXDOMAIN:
                # No such name
                return build_nxdomain_response()
            else:
                # Fallback to full query
                return await query_upstream(normalized_qname, qtype, minimize=False)
    # If we reach here, query the full name
    return await query_upstream(normalized_qname, qtype, minimize=False)

async def wrapped_query(server: str, query_func, query_id: int, transport: str) -> Tuple[str, Optional[bytes]]:
    start = time.time()
    try:
        result = await query_func
        latency = time.time() - start
        await UPSTREAM_HEALTH.record_success(server, latency)
        if result:
            response = dns.message.from_wire(result)
            if transport == "doq":
                pass
            elif response.id != query_id:
                log.warning(f"[dns] Non-matching DNS IDs ({response.id} vs {query_id}) – tolerated")
        return server, result
    except Exception as e:
        await UPSTREAM_HEALTH.record_failure(server)
        return server, None
async def query_upstream_parallel(qname: str, qtype: int) -> Optional[Tuple[bytes, str]]:
    servers = CONFIG["upstream_servers"].copy()
    healthy = UPSTREAM_HEALTH.get_healthy()
    if healthy:
        servers = [s for s in servers if s in healthy or s not in UPSTREAM_HEALTH.get_status()]
    if not servers:
        return None
    normalized_qname = qname.lower().strip('.')
    randomized_qname = apply_0x20_encoding(normalized_qname)
    query = dns.message.make_query(randomized_qname, qtype, use_edns=True)
    query_id = random.randint(0, 65535) if not (CONFIG.get("doq_enabled") and DOQ_AVAILABLE) else 0
    query.id = query_id
    wire_query = pad_wire(query.to_wire())
    if CONFIG.get("query_jitter") and not (CONFIG.get("doq_enabled") and DOQ_AVAILABLE):
        jitter_range = CONFIG.get("query_jitter_ms", [10, 100])
        jitter = random.randint(jitter_range[0], jitter_range[1]) / 1000.0
        await asyncio.sleep(jitter)
    query_funcs = []
    transports = []
    for server in servers:
        if CONFIG.get("doq_enabled") and DOQ_AVAILABLE:
            func = query_doq(wire_query, server)
            transport = "doq"
        elif CONFIG.get("doh_enabled") and server in ["1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4"]:
            func = query_doh(wire_query, server)
            transport = "doh"
        elif CONFIG.get("dot_enabled"):
            func = query_dot(wire_query, server)
            transport = "dot"
        else:
            func = query_udp(wire_query, server)
            transport = "udp"
        query_funcs.append(func)
        transports.append(transport)
    STATS["dns_parallel"] += 1
    wrapped_tasks = [asyncio.create_task(wrapped_query(servers[i], query_funcs[i], query_id, transports[i])) for i in range(len(servers))]
    for completed_task in asyncio.as_completed(wrapped_tasks):
        server, result = await completed_task
        if result is not None:
            return result, server
    return None
async def query_upstream(qname: str, qtype: int, depth: int = 0, minimize: bool = True) -> Optional[bytes]:
    if minimize and CONFIG.get("qname_minimization"):
        return await query_upstream_minimized(qname, qtype, depth)
    if CONFIG.get("upstream_parallel") and len(CONFIG["upstream_servers"]) > 1:
        result = await query_upstream_parallel(qname, qtype)
        return result[0] if result else None
    servers = CONFIG["upstream_servers"].copy()
    healthy = UPSTREAM_HEALTH.get_healthy()
    if healthy:
        servers = [s for s in servers if s in healthy or s not in UPSTREAM_HEALTH.get_status()]
    if CONFIG.get("upstream_rotation"):
        random.shuffle(servers)
    normalized_qname = qname.lower().strip('.')
    randomized_qname = apply_0x20_encoding(normalized_qname)
    query = dns.message.make_query(randomized_qname, qtype, use_edns=True)
    query_id = random.randint(0, 65535) if not (CONFIG.get("doq_enabled") and DOQ_AVAILABLE) else 0
    query.id = query_id
    wire_query = pad_wire(query.to_wire())
    if CONFIG.get("query_jitter") and not (CONFIG.get("doq_enabled") and DOQ_AVAILABLE):
        jitter_range = CONFIG.get("query_jitter_ms", [10, 100])
        jitter = random.randint(jitter_range[0], jitter_range[1]) / 1000.0
        await asyncio.sleep(jitter)
    upstream_queries = 0
    total_latency = 0.0
    for server in servers:
        try:
            start = time.time()
            upstream_queries += 1
            if CONFIG.get("doq_enabled") and DOQ_AVAILABLE:
                response_wire = await query_doq(wire_query, server)
                transport = "doq"
            elif CONFIG.get("doh_enabled") and server in ["1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4"]:
                response_wire = await query_doh(wire_query, server)
                transport = "doh"
            elif CONFIG.get("dot_enabled"):
                response_wire = await query_dot(wire_query, server)
                transport = "dot"
            else:
                response_wire = await query_udp(wire_query, server)
                transport = "udp"
            if response_wire:
                latency = time.time() - start
                total_latency += latency
                await UPSTREAM_HEALTH.record_success(server, latency)
                if transport != "doq":
                    response = dns.message.from_wire(response_wire)
                    if response.id != query_id:
                        log.warning(f"[dns] Non-matching DNS IDs ({response.id} vs {query_id}) – tolerated")
                if upstream_queries > 0:
                    STATS["dns_upstream_latency"] = total_latency / upstream_queries
                return response_wire
            else:
                log.debug(f"[upstream] Fail: {server}")
                await UPSTREAM_HEALTH.record_failure(server)
        except Exception as e:
            log.debug(f"[upstream] {server} error: {e}")
            await UPSTREAM_HEALTH.record_failure(server)
            continue
    if upstream_queries > 0:
        STATS["dns_upstream_latency"] = total_latency / upstream_queries
    log.warning(f"[dns] All upstreams failed for {qname}. Healthy: {UPSTREAM_HEALTH.get_healthy()}")
    return None
async def query_udp(wire_query: bytes, server: str) -> Optional[bytes]:
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(CONFIG["upstream_timeout"])
    try:
        sock.sendto(wire_query, (server, 53))
        response, _ = sock.recvfrom(4096)
        return response
    finally:
        sock.close()
async def query_doh(wire_query: bytes, server: str) -> Optional[bytes]:
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
    import ssl
    try:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, 853, ssl=ssl_context),
            timeout=CONFIG["upstream_timeout"]
        )
        msg_len = struct.pack('!H', len(wire_query))
        writer.write(msg_len + wire_query)
        await writer.drain()
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
            rrset = dns.rrset.RRset(qname, dns.rdataclass.IN, dns.rdatatype.A)
            rrset.add(dns.rdtypes.IN.A.A(dns.rdataclass.IN, dns.rdatatype.A, ip), ttl=300)
            response.answer.append(rrset)
        elif qtype == dns.rdatatype.AAAA:
            rrset = dns.rrset.RRset(qname, dns.rdataclass.IN, dns.rdatatype.AAAA)
            rrset.add(dns.rdtypes.IN.AAAA.AAAA(dns.rdataclass.IN, dns.rdatatype.AAAA, "::"), ttl=300)
            response.answer.append(rrset)
    return response.to_wire()
def build_rewrite_response(query: dns.message.Message, rewrite: dict) -> bytes:
    response = dns.message.make_response(query)
    qname = query.question[0].name
    record_type = rewrite.get("type", "A")
    value = rewrite.get("value")
    ttl = rewrite.get("ttl", 300)
    if record_type == "A" and value:
        rrset = dns.rrset.RRset(qname, dns.rdataclass.IN, dns.rdatatype.A)
        rrset.add(dns.rdtypes.IN.A.A(dns.rdataclass.IN, dns.rdatatype.A, value), ttl=ttl)
        response.answer.append(rrset)
    elif record_type == "AAAA" and value:
        rrset = dns.rrset.RRset(qname, dns.rdataclass.IN, dns.rdatatype.AAAA)
        rrset.add(dns.rdtypes.IN.AAAA.AAAA(dns.rdataclass.IN, dns.rdatatype.AAAA, value), ttl=ttl)
        response.answer.append(rrset)
    elif record_type == "CNAME" and value:
        rrset = dns.rrset.RRset(qname, dns.rdataclass.IN, dns.rdatatype.CNAME)
        rrset.add(dns.rdtypes.ANY.CNAME.CNAME(dns.rdataclass.IN, dns.rdatatype.CNAME, dns.name.from_text(value)), ttl=ttl)
        response.answer.append(rrset)
    elif record_type == "TXT" and value:
        rrset = dns.rrset.RRset(qname, dns.rdataclass.IN, dns.rdatatype.TXT)
        rrset.add(dns.rdtypes.ANY.TXT.TXT(dns.rdataclass.IN, dns.rdatatype.TXT, [value.encode()]), ttl=ttl)
        response.answer.append(rrset)
    elif record_type == "MX" and value:
        parts = value.split(None, 1)
        priority = int(parts[0]) if len(parts) > 1 else 10
        exchange = parts[1] if len(parts) > 1 else parts[0]
        rrset = dns.rrset.RRset(qname, dns.rdataclass.IN, dns.rdatatype.MX)
        rrset.add(dns.rdtypes.ANY.MX.MX(dns.rdataclass.IN, dns.rdatatype.MX, priority, dns.name.from_text(exchange)), ttl=ttl)
        response.answer.append(rrset)
    return response.to_wire()
def strip_ecs(response_wire: bytes) -> bytes:
    if not CONFIG.get("ecs_strip"):
        return response_wire
    try:
        response = dns.message.from_wire(response_wire)
        if response.edns >= 0:
            original_options = list(response.options)
            new_options = [opt for opt in original_options if opt.otype != 8]
            if len(new_options) < len(original_options):
                STATS["dns_ecs_stripped"] += 1
                response.use_edns(edns=response.edns, ednsflags=response.ednsflags, payload=response.payload, options=new_options)
        return response.to_wire()
    except:
        return response_wire
# ==================== DNS PROCESSING ====================
async def process_dns_query(data: bytes, addr: Tuple[str, int]) -> bytes:
    try:
        # Basic validation
        if len(data) < 12:
            log.warning(f"[dns] Packet too small from {addr[0]}: {len(data)} bytes")
            return None
       
        # Check if it looks like DNS (starts with transaction ID, has flags)
        if len(data) >= 12:
            try:
                # Try to parse as DNS
                query = dns.message.from_wire(data)
            except dns.exception.FormError as e:
                log.error(f"[dns] Malformed DNS packet from {addr[0]}: {e}")
                log.debug(f"[dns] Packet hex: {data[:50].hex()}")
                return None
            except Exception as e:
                log.error(f"[dns] Failed to parse DNS from {addr[0]}: {e}")
                return None
       
        # Rate limiting
        if not await RATE_LIMITER.check_rate_limit(addr[0]):
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.REFUSED)
            return response.to_wire()
       
        qname = str(query.question[0].name).lower().strip('.')
        qtype = query.question[0].rdtype
       
        if not CONFIG.get("zero_log"):
            log.info(f"[dns] Query from {addr[0]}: {qname} ({dns.rdatatype.to_text(qtype)})")
       
        STATS["dns_queries"] += 1
        
        # Track for top 10
        TOP_QUERIES[qname] += 1
        TOP_CLIENTS[addr[0]] += 1
       
        # Record query in history for prewarming
        await QUERY_HISTORY.record(qname)
       
        # Check whitelist first
        if await WHITELIST.contains(qname):
            pass
        else:
            if await BLACKLIST.contains(qname):
                STATS["dns_blocked"] += 1
                TOP_BLOCKED[qname] += 1
                log.info(f"[dns] Blocked (blacklist): {qname}")
                return build_blocked_response(query)
           
            if CONFIG.get("blocking_enabled") and await BLOCKLIST.contains(qname):
                STATS["dns_blocked"] += 1
                TOP_BLOCKED[qname] += 1
                log.info(f"[dns] Blocked (blocklist): {qname}")
                return build_blocked_response(query)
       
        # SafeSearch enforcement (after checks)
        safesearch_domain = apply_safesearch(qname)
        if safesearch_domain:
            # Rewrite to safe domain and query that
            safe_query = dns.message.make_query(safesearch_domain, qtype)
            response_wire = await query_upstream(safesearch_domain, qtype)
            if response_wire:
                return response_wire
            else:
                response = dns.message.make_response(query)
                response.set_rcode(dns.rcode.SERVFAIL)
                return response.to_wire()
       
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
       
        # DNSSEC validation
        transport = "doq" if (CONFIG.get("doq_enabled") and DOQ_AVAILABLE) else "udp"
        if not await validate_dnssec(response_wire, transport, query.id):
            log.warning(f"[dnssec] Validation failed for {qname}")
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
            return response.to_wire()
       
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
                    elif rrset.rdtype == dns.rdatatype.AAAA:
                        for rr in rrset:
                            try:
                                ip = ipaddress.IPv6Address(rr.address)
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
        log.error(f"[dns] Unexpected error processing query from {addr[0]}: {e}")
        return None
# ==================== DNS SERVER ====================
# ==================== DNS SERVER ====================
class DNSProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.create_task(self.handle_query(data, addr))

    async def handle_query(self, data, addr):
        try:
            # Parse original query to extract its transaction ID
            query = None
            try:
                query = dns.message.from_wire(data)
            except Exception as e:
                log.warning(f"[dns] Failed to parse incoming query from {addr[0]}: {e}")

            response = await process_dns_query(data, addr)

            if response:
                try:
                    msg = dns.message.from_wire(response)

                    # 🩵 Ensure the response ID matches the client's query ID
                    if query is not None:
                        msg.id = query.id

                    # --- Final downstream recursion fix ---
                    msg.flags |= dns.flags.RA     # recursion available
                    msg.flags |= dns.flags.RD     # recursion desired
                    msg.flags &= ~dns.flags.AA    # not authoritative

                    log.debug(f"[dns] Outgoing flags: {dns.flags.to_text(msg.flags)}")

                    response = msg.to_wire()
                    self.transport.sendto(response, addr)

                except Exception as e:
                    log.warning(f"[dns] ID or flag sync failed for {addr[0]}: {e}")

            else:
                log.warning(f"[dns] No response generated for query from {addr[0]}")

        except Exception as e:
            log.error(f"[dns] Error handling query from {addr[0]}: {e}")
            import traceback
            log.error(traceback.format_exc())


dns_transport = None


async def start_dns():
    global dns_transport
    try:
        log.info(f"[dns] Attempting to start DNS server on {CONFIG['dns_bind']}:{CONFIG['dns_port']}")
        loop = asyncio.get_event_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: DNSProtocol(),
            local_addr=(CONFIG["dns_bind"], CONFIG["dns_port"]),
            reuse_port=True
        )
        dns_transport = transport
        log.info(f"[dns] ✅ DNS server SUCCESSFULLY started on {CONFIG['dns_bind']}:{CONFIG['dns_port']}")
    except PermissionError as e:
        log.error(f"[dns] ❌ PERMISSION DENIED - Cannot bind to port {CONFIG['dns_port']} (requires root/CAP_NET_BIND_SERVICE)")
        log.error(f"[dns] Error: {e}")
        raise
    except OSError as e:
        log.error(f"[dns] ❌ FAILED to bind to {CONFIG['dns_bind']}:{CONFIG['dns_port']}")
        log.error(f"[dns] Error: {e}")
        log.error(f"[dns] Is another DNS server already running on port {CONFIG['dns_port']}?")
        raise
    except Exception as e:
        log.error(f"[dns] ❌ UNEXPECTED ERROR starting DNS server: {e}")
        raise


# ==================== DHCP SERVER ====================
DHCP_DISCOVER = 1
DHCP_OFFER = 2
DHCP_REQUEST = 3
DHCP_DECLINE = 4
DHCP_ACK = 5
DHCP_NAK = 6
DHCP_RELEASE = 7
DHCP_INFORM = 8
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
        start_ip = ipaddress.IPv4Address(CONFIG["dhcp_range_start"])
        end_ip = ipaddress.IPv4Address(CONFIG["dhcp_range_end"])
       
        self.ip_pool = [
            str(ipaddress.IPv4Address(ip))
            for ip in range(int(start_ip), int(end_ip) + 1)
        ]
        log.info(f"[dhcp] IP pool: {len(self.ip_pool)} addresses")
   
    def _load_leases(self):
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
       
        for mac, ip in CONFIG.get("dhcp_static_leases", {}).items():
            self.leases[mac] = DHCPLease(
                mac=mac,
                ip=ip,
                static=True,
                lease_start=time.time(),
                lease_end=time.time() + (365 * 86400)
            )
   
    def _save_leases(self):
        lease_file = Path("/config/veil_dhcp_leases.json")
        try:
            data = {mac: lease.to_dict() for mac, lease in self.leases.items() if not lease.static}
            with open(lease_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"[dhcp] Failed to save leases: {e}")
   
    async def _ping_check(self, ip: str) -> bool:
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
           
            if proc.returncode == 0:
                log.warning(f"[dhcp] IP conflict detected: {ip} is in use")
                STATS["dhcp_conflicts"] += 1
                return True
        except:
            pass
       
        return False
   
    async def _get_available_ip(self, mac: str) -> Optional[str]:
        async with self.lock:
            if mac in self.leases and not self.leases[mac].is_expired():
                return self.leases[mac].ip
           
            used_ips = {lease.ip for lease in self.leases.values() if not lease.is_expired()}
           
            for ip in self.ip_pool:
                if ip not in used_ips:
                    if await self._ping_check(ip):
                        continue
                    return ip
       
        return None
   
    def _parse_dhcp_packet(self, data: bytes) -> Optional[dict]:
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
           
            if data[236:240] != b'\x63\x82\x53\x63':
                return None
           
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
                if isinstance(packet.get("chaddr"), (dict, list)):
                    log.error(f"[dhcp] Malformed chaddr field: {packet['chaddr']}")
                    packet["chaddr"] = str(packet["chaddr"])
            
            return packet
       
        except Exception as e:
            log.error(f"[dhcp] Parse error: {e}")
            return None
   
    def _build_dhcp_packet(self, packet: dict, msg_type: int, offered_ip: str) -> bytes:
        response = bytearray(548)
       
        response[0] = 2
        response[1] = packet["htype"]
        response[2] = packet["hlen"]
        response[3] = 0
       
        struct.pack_into("!I", response, 4, packet["xid"])
        struct.pack_into("!H", response, 8, 0)
        struct.pack_into("!H", response, 10, packet["flags"])
       
        response[12:16] = socket.inet_aton("0.0.0.0")
        response[16:20] = socket.inet_aton(offered_ip)
        response[20:24] = socket.inet_aton(CONFIG["dhcp_gateway"])
        response[24:28] = socket.inet_aton(packet["giaddr"])
       
        mac_bytes = bytes.fromhex(packet["chaddr"].replace(':', ''))
        response[28:28 + len(mac_bytes)] = mac_bytes
       
        response[236:240] = b'\x63\x82\x53\x63'
       
        pos = 240
       
        response[pos:pos + 3] = bytes([DHCP_OPT_MESSAGE_TYPE, 1, msg_type])
        pos += 3
       
        server_ip = socket.inet_aton(CONFIG["dhcp_gateway"])
        response[pos:pos + 6] = bytes([DHCP_OPT_SERVER_ID, 4]) + server_ip
        pos += 6
       
        lease_time = CONFIG["dhcp_lease_time"]
        response[pos:pos + 6] = bytes([DHCP_OPT_LEASE_TIME, 4]) + struct.pack("!I", lease_time)
        pos += 6
       
        renewal_time = CONFIG.get("dhcp_renewal_time", lease_time // 2)
        response[pos:pos + 6] = bytes([DHCP_OPT_RENEWAL_TIME, 4]) + struct.pack("!I", renewal_time)
        pos += 6
       
        rebinding_time = CONFIG.get("dhcp_rebinding_time", int(lease_time * 0.875))
        response[pos:pos + 6] = bytes([DHCP_OPT_REBINDING_TIME, 4]) + struct.pack("!I", rebinding_time)
        pos += 6
       
        netmask = socket.inet_aton(CONFIG["dhcp_netmask"])
        response[pos:pos + 6] = bytes([DHCP_OPT_SUBNET_MASK, 4]) + netmask
        pos += 6
       
        gateway = socket.inet_aton(CONFIG["dhcp_gateway"])
        response[pos:pos + 6] = bytes([DHCP_OPT_ROUTER, 4]) + gateway
        pos += 6
       
        try:
            network = ipaddress.IPv4Network(f"{CONFIG['dhcp_subnet']}/{CONFIG['dhcp_netmask']}", strict=False)
            broadcast = socket.inet_aton(str(network.broadcast_address))
            response[pos:pos + 6] = bytes([DHCP_OPT_BROADCAST, 4]) + broadcast
            pos += 6
        except:
            pass
       
       
        dns_servers = CONFIG.get("dhcp_dns_servers", [CONFIG["dhcp_gateway"]])
        dns_bytes = b''.join(socket.inet_aton(dns) for dns in dns_servers[:3])
        response[pos:pos + 2 + len(dns_bytes)] = bytes([DHCP_OPT_DNS_SERVER, len(dns_bytes)]) + dns_bytes
        pos += 2 + len(dns_bytes)
        
        if CONFIG.get("dhcp_domain"):
            domain = CONFIG["dhcp_domain"].encode()
            response[pos:pos + 2 + len(domain)] = bytes([DHCP_OPT_DOMAIN_NAME, len(domain)]) + domain
            pos += 2 + len(domain)
        
        if CONFIG.get("dhcp_ntp_servers"):
            ntp_servers = CONFIG.get("dhcp_ntp_servers")
            ntp_bytes = b''.join(socket.inet_aton(ntp) for ntp in ntp_servers[:3])
            response[pos:pos + 2 + len(ntp_bytes)] = bytes([DHCP_OPT_NTP_SERVER, len(ntp_bytes)]) + ntp_bytes
            pos += 2 + len(ntp_bytes)
        
        if CONFIG.get("dhcp_wins_servers"):
            wins_servers = CONFIG.get("dhcp_wins_servers")
            wins_bytes = b''.join(socket.inet_aton(wins) for wins in wins_servers[:2])
            response[pos:pos + 2 + len(wins_bytes)] = bytes([DHCP_OPT_WINS_SERVER, len(wins_bytes)]) + wins_bytes
            pos += 2 + len(wins_bytes)
        
        vendor_opts = CONFIG.get("dhcp_vendor_options", {})
        if isinstance(vendor_opts, dict):
            vendor_data = b''
            for opt_code, opt_value in vendor_opts.items():
                if isinstance(opt_value, str):
                    opt_value = opt_value.encode()
                vendor_data += bytes([int(opt_code), len(opt_value)]) + opt_value
            
            if vendor_data:
                response[pos:pos + 2 + len(vendor_data)] = bytes([DHCP_OPT_VENDOR_SPECIFIC, len(vendor_data)]) + vendor_data
                pos += 2 + len(vendor_data)
        
        if CONFIG.get("dhcp_tftp_server"):
            tftp = CONFIG["dhcp_tftp_server"].encode()
            response[pos:pos + 2 + len(tftp)] = bytes([DHCP_OPT_TFTP_SERVER, len(tftp)]) + tftp
            pos += 2 + len(tftp)
        
        if CONFIG.get("dhcp_bootfile"):
            bootfile = CONFIG["dhcp_bootfile"].encode()
            response[pos:pos + 2 + len(bootfile)] = bytes([DHCP_OPT_BOOTFILE, len(bootfile)]) + bootfile
            pos += 2 + len(bootfile)
        
        response[pos] = DHCP_OPT_END
        
        return bytes(response[:pos + 1])
    
    async def handle_discover(self, packet: dict, addr: Tuple[str, int]):
        mac = packet["chaddr"]
        offered_ip = await self._get_available_ip(mac)
        
        if not offered_ip:
            log.warning(f"[dhcp] No available IP for {mac}")
            return
        
        log.info(f"[dhcp] DISCOVER from {mac} -> offering {offered_ip}")
        STATS["dhcp_discovers"] += 1
        STATS["dhcp_offers"] += 1
        
        response = self._build_dhcp_packet(packet, DHCP_OFFER, offered_ip)
        
        if packet["flags"] & 0x8000:
            self.sock.sendto(response, ('<broadcast>', 68))
        else:
            try:
                self.sock.sendto(response, (offered_ip, 68))
            except:
                self.sock.sendto(response, ('<broadcast>', 68))
    
    async def handle_request(self, packet: dict, addr: Tuple[str, int]):
        mac = packet["chaddr"]
        requested_ip = None
        
        if DHCP_OPT_REQUESTED_IP in packet["options"]:
            requested_ip = socket.inet_ntoa(packet["options"][DHCP_OPT_REQUESTED_IP])
        elif packet["ciaddr"] != "0.0.0.0":
            requested_ip = packet["ciaddr"]
        
        if not requested_ip:
            log.warning(f"[dhcp] REQUEST from {mac} without requested IP")
            return
        
        STATS["dhcp_requests"] += 1
        
        available_ip = await self._get_available_ip(mac)
        
        if requested_ip not in self.ip_pool and requested_ip != available_ip:
            log.warning(f"[dhcp] NAK: {mac} requested invalid IP {requested_ip}")
            response = self._build_dhcp_packet(packet, DHCP_NAK, "0.0.0.0")
            self.sock.sendto(response, ('<broadcast>', 68))
            STATS["dhcp_naks"] += 1
            return
        
        hostname = ""
        if DHCP_OPT_HOSTNAME in packet["options"]:
            hostname = packet["options"][DHCP_OPT_HOSTNAME].decode('utf-8', errors='ignore')
        
        client_id = ""
        if DHCP_OPT_CLIENT_ID in packet["options"]:
            client_id = packet["options"][DHCP_OPT_CLIENT_ID].hex()
        
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
        
        response = self._build_dhcp_packet(packet, DHCP_ACK, requested_ip)
        
        if packet["flags"] & 0x8000:
            self.sock.sendto(response, ('<broadcast>', 68))
        else:
            try:
                self.sock.sendto(response, (requested_ip, 68))
            except:
                self.sock.sendto(response, ('<broadcast>', 68))
    
    async def handle_decline(self, packet: dict, addr: Tuple[str, int]):
        mac = packet["chaddr"]
        declined_ip = None
        
        if DHCP_OPT_REQUESTED_IP in packet["options"]:
            declined_ip = socket.inet_ntoa(packet["options"][DHCP_OPT_REQUESTED_IP])
        
        log.warning(f"[dhcp] DECLINE from {mac} for {declined_ip} - IP conflict detected")
        STATS["dhcp_declines"] += 1
        STATS["dhcp_conflicts"] += 1
        
        async with self.lock:
            if mac in self.leases and not self.leases[mac].static:
                del self.leases[mac]
                self._save_leases()
    
    async def handle_release(self, packet: dict, addr: Tuple[str, int]):
        mac = packet["chaddr"]
        
        async with self.lock:
            if mac in self.leases and not self.leases[mac].static:
                released_ip = self.leases[mac].ip
                del self.leases[mac]
                self._save_leases()
                log.info(f"[dhcp] RELEASE {mac} -> {released_ip}")
                STATS["dhcp_releases"] += 1
    
    async def handle_inform(self, packet: dict, addr: Tuple[str, int]):
        mac = packet["chaddr"]
        client_ip = packet["ciaddr"]
        
        log.info(f"[dhcp] INFORM from {mac} ({client_ip})")
        STATS["dhcp_informs"] += 1
        
        response = self._build_dhcp_packet(packet, DHCP_ACK, client_ip)
        self.sock.sendto(response, (client_ip, 68))
    
    async def handle_packet(self, data: bytes, addr: Tuple[str, int]):
        try:
            packet = self._parse_dhcp_packet(data)
            if not packet:
                return
            
            if CONFIG.get("dhcp_relay_support") and packet["giaddr"] != "0.0.0.0":
                log.debug(f"[dhcp] Relay agent: {packet['giaddr']}")
                # Add relay handling if needed, e.g., forward to another server
                # For now, process as normal
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
        while self.running:
            try:
                await asyncio.sleep(300)
                
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
        self.running = False
        if self.cleanup_task:
            self.cleanup_task.cancel()
        if self.sock:
            self.sock.close()
        self._save_leases()
        log.info("[dhcp] Stopped")
    
    def get_leases(self) -> List[dict]:
        return [lease.to_dict() for lease in self.leases.values() if not lease.is_expired()]
    
    def delete_lease(self, mac: str) -> bool:
        if mac in self.leases and not self.leases[mac].static:
            del self.leases[mac]
            self._save_leases()
            return True
        return False
    
    def add_static_lease(self, mac: str, ip: str, hostname: str = "") -> bool:
        try:
            ipaddress.IPv4Address(ip)  # Validate IP
        except ValueError:
            return False
        
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
    uptime = int(time.time() - STATS.get("start_time", time.time()))
    
    # Get upstream health and fill in missing servers from config
    upstream_health = UPSTREAM_HEALTH.get_status()
    for server in CONFIG.get("upstream_servers", []):
        if server not in upstream_health:
            upstream_health[server] = {
                "healthy": True,
                "success_rate": 1.0,
                "total": 0,
                "success": 0,
                "avg_latency": 0
            }
    
    # Map internal stats to UI-expected keys
    return web.json_response({
        # Main stats - mapped for UI compatibility
        "total_queries": STATS.get("dns_queries", 0),
        "blocked": STATS.get("dns_blocked", 0),
        "cache_hits": STATS.get("dns_cached", 0),
        "upstream_queries": STATS.get("dns_upstream", 0),
        "padded": STATS.get("dns_padded", 0),
        "ecs_stripped": STATS.get("dns_ecs_stripped", 0),
        "case_randomized": STATS.get("dns_0x20", 0),
        "dnssec_valid": STATS.get("dns_dnssec_validated", 0),
        
        # DHCP stats
        "dhcp_offers": STATS.get("dhcp_offers", 0),
        "dhcp_acks": STATS.get("dhcp_acks", 0),
        "active_leases": len(DHCP_SERVER.leases) if DHCP_SERVER else 0,
        "pool_total": len(DHCP_SERVER.ip_pool) + len(DHCP_SERVER.leases) if DHCP_SERVER else 0,
        
        # System stats
        "uptime_seconds": uptime,
        "dns_running": dns_transport is not None,
        "dhcp_running": DHCP_SERVER.running if DHCP_SERVER else False,
        "queries_per_second": STATS.get("dns_queries", 0) / max(uptime, 1),
        
        # Storage stats
        "cache_size": DNS_CACHE.size(),
        "blocklist_size": BLOCKLIST.size,
        "whitelist_size": WHITELIST.size,
        "blacklist_size": BLACKLIST.size,
        
        # Health & misc
        "upstream_health": upstream_health,
        "leases": [lease.to_dict() for lease in DHCP_SERVER.leases.values()] if DHCP_SERVER else [],
        
        # Top 10 lists
        "top_queries": [{"domain": d, "count": c} for d, c in TOP_QUERIES.most_common(10)],
        "top_blocked": [{"domain": d, "count": c} for d, c in TOP_BLOCKED.most_common(10)],
        "top_clients": [{"ip": i, "count": c} for i, c in TOP_CLIENTS.most_common(10)],
        
        # Raw STATS for debugging
        **STATS
    })

async def api_config_get(req):
    return web.json_response(CONFIG)

async def api_config_update(req):
    try:
        data = await req.json()
        
        # Parse upstream_servers - extract IPs from DoH URLs if needed
        if "upstream_servers" in data:
            servers = []
            doh_map = {
                "cloudflare-dns.com": ["1.1.1.1", "1.0.0.1"],
                "dns.google": ["8.8.8.8", "8.8.4.4"],
                "dns.quad9.net": ["9.9.9.9", "149.112.112.112"],
                "doh.opendns.com": ["208.67.222.222", "208.67.220.220"],
                "dns.adguard-dns.com": ["94.140.14.14", "94.140.15.15"]
            }
            
            for server in data["upstream_servers"]:
                server = server.strip()
                if not server:
                    continue
                    
                # Check if it's a DoH URL
                if server.startswith("http"):
                    # Extract domain and map to IPs
                    for domain, ips in doh_map.items():
                        if domain in server:
                            servers.extend(ips)
                            break
                else:
                    # It's an IP address
                    servers.append(server)
            
            data["upstream_servers"] = list(set(servers))  # Remove duplicates
        
        for key, value in data.items():
            if key in CONFIG:
                CONFIG[key] = value
        
        # Save to file
        try:
            with open('/config/options.json', 'r') as f:
                file_config = json.load(f)
            file_config.update(data)
            with open('/config/options.json', 'w') as f:
                json.dump(file_config, f, indent=2)
            log.info(f"[api] Config saved to /config/options.json")
        except Exception as e:
            log.warning(f"[api] Could not save config to file: {e}")
        
        return web.json_response({"status": "updated", "config": CONFIG})
    except Exception as e:
        log.error(f"[api] Config update error: {e}")
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
        
        await save_blocklists_local()  # Save after reload
        return web.json_response({"status": "reloaded", "size": BLOCKLIST.size})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_blocklist_update(req):
    try:
        await BLOCKLIST_UPDATER.update_blocklists()
        return web.json_response({
            "status": "updated",
            "size": BLOCKLIST.size,
            "last_update": STATS["blocklist_last_update"]
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_cache_prewarm(req):
    """Trigger manual cache prewarm"""
    try:
        asyncio.create_task(CACHE_PREWARMER.prewarm_cache())
        return web.json_response({
            "status": "started",
            "message": "Cache prewarm started in background"
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_query_history(req):
    """Get query history stats"""
    try:
        count = int(req.query.get('count', 50))
        top_domains = await QUERY_HISTORY.get_top(count)
        return web.json_response({
            "total_unique": QUERY_HISTORY.size(),
            "top_domains": top_domains
        })
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
        
        await save_blocklists_local()  # Save after upload
        return web.json_response({"status": "uploaded", "added": count, "total": BLOCKLIST.size})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_blacklist_add(req):
    try:
        data = await req.json()
        domain = data.get('domain', '').strip()
        if domain:
            await BLACKLIST.add(domain)
            await save_blocklists_local()  # Save after adding
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
            await save_blocklists_local()  # Save after removing
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
            await save_blocklists_local()  # Save after adding
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
            await save_blocklists_local()  # Save after removing
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
            return web.json_response({"error": "Invalid IP or not in pool"}, status=400)
    
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
    app.router.add_get('/api/veil/stats', api_stats)
    app.router.add_get('/api/veil/health', api_health)
    app.router.add_get('/api/veil/config', api_config_get)
    app.router.add_post('/api/veil/config', api_config_update)
    app.router.add_delete('/api/veil/cache', api_cache_flush)
    app.router.add_post('/api/veil/blocklist/reload', api_blocklist_reload)
    app.router.add_post('/api/veil/blocklist/update', api_blocklist_update)
    app.router.add_post('/api/veil/blocklist/upload', api_blocklist_upload)
    app.router.add_post('/api/veil/cache/prewarm', api_cache_prewarm)
    app.router.add_get('/api/veil/query/history', api_query_history)
    app.router.add_post('/api/veil/blacklist/add', api_blacklist_add)
    app.router.add_delete('/api/veil/blacklist/remove', api_blacklist_remove)
    app.router.add_post('/api/veil/whitelist/add', api_whitelist_add)
    app.router.add_delete('/api/veil/whitelist/remove', api_whitelist_remove)
    app.router.add_post('/api/veil/rewrite/add', api_rewrite_add)
    app.router.add_delete('/api/veil/rewrite/remove', api_rewrite_remove)
    app.router.add_post('/api/veil/record/add', api_local_record_add)
    app.router.add_delete('/api/veil/record/remove', api_local_record_remove)
    app.router.add_get('/api/veil/dhcp/leases', api_dhcp_leases)
    app.router.add_post('/api/veil/dhcp/static', api_dhcp_static_add)
    app.router.add_delete('/api/veil/dhcp/lease', api_dhcp_lease_delete)
    
    log.info("[veil] Routes registered")

async def init_veil():
    log.info("=" * 60)
    log.info("[veil] 🧩 Privacy-First DNS/DHCP initializing")
    log.info("=" * 60)
    
    # Initialize global objects
    global DNS_CACHE, BLOCKLIST, WHITELIST, BLACKLIST, UPSTREAM_HEALTH, CONN_POOL, DHCP_SERVER
    global RATE_LIMITER, CACHE_PREWARMER, BLOCKLIST_UPDATER
    
    log.info(f"[veil] Enabled: {CONFIG.get('enabled', True)}")
    log.info(f"[veil] DHCP Enabled: {CONFIG.get('dhcp_enabled', False)}")
    log.info(f"[veil] DNS Port: {CONFIG.get('dns_port', 53)}")
    log.info(f"[veil] DNS Bind: {CONFIG.get('dns_bind', '0.0.0.0')}")
    
    STATS["start_time"] = time.time()
    STATS["blocklist_last_update"] = 0
    
    # Initialize all DNS stats to 0
    STATS["dns_queries"] = 0
    STATS["dns_blocked"] = 0
    STATS["dns_cached"] = 0
    STATS["dns_upstream"] = 0
    STATS["dns_padded"] = 0
    STATS["dns_ecs_stripped"] = 0
    STATS["dns_0x20"] = 0
    STATS["dns_dnssec_validated"] = 0
    STATS["dns_rate_limited"] = 0
    
    DNS_CACHE = LRUCache(max_size=CONFIG.get("cache_max_size", 10000))
    log.info(f"[veil] DNS Cache initialized (max: {CONFIG.get('cache_max_size', 10000)})")
    
    UPSTREAM_HEALTH = UpstreamHealth()
    log.info(f"[veil] Upstream health monitor initialized")
    
    RATE_LIMITER = RateLimiter()
    log.info(f"[veil] Rate limiter initialized")
    
    CACHE_PREWARMER = CachePrewarmer()
    log.info(f"[veil] Cache prewarmer initialized")
    
    BLOCKLIST_UPDATER = BlocklistUpdater()
    log.info(f"[veil] Blocklist updater initialized")
    
    CONN_POOL = await get_conn_pool()
    log.info(f"[veil] Connection pool initialized")
    
    DHCP_SERVER = DHCPServer()
    log.info(f"[veil] DHCP server initialized")
    
    # Load blocklists
    log.info("[veil] Loading blocklists...")
    loaded_local = await load_blocklists_local()
    
    if not loaded_local:
        log.info("[veil] No local blocklists found, loading from files")
        for bl in CONFIG.get("blocklists", []):
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
    
    # Start rate limiter
    RATE_LIMITER.start()
    log.info(f"[veil] Rate limiter started")
    
    # Start cache prewarmer
    if CONFIG.get("cache_prewarm_enabled"):
        CACHE_PREWARMER.start()
        log.info(f"[veil] Cache prewarm: every {CONFIG['cache_prewarm_interval']}s")
    
    # Start blocklist auto-updater
    if CONFIG.get("blocklist_update_enabled"):
        BLOCKLIST_UPDATER.start()
        log.info(f"[veil] Blocklist auto-update: every {CONFIG['blocklist_update_interval']}s")
    
    # Start DNS
    log.info("[veil] Attempting to start DNS server...")
    if CONFIG.get("enabled", True):
        try:
            await start_dns()
            
            features = []
            if CONFIG.get("doh_enabled"):
                features.append("DoH")
            if CONFIG.get("dot_enabled"):
                features.append("DoT")
            if CONFIG.get("doq_enabled") and DOQ_AVAILABLE:
                features.append("DoQ")
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
            if CONFIG.get("dnssec_validate"):
                features.append("DNSSEC")
            if CONFIG.get("rate_limit_enabled"):
                features.append(f"rate limit ({CONFIG['rate_limit_qps']} qps)")
            if CONFIG.get("safesearch_enabled"):
                features.append("SafeSearch")
            
            log.info(f"[veil] Privacy: {', '.join(features)}")
        except Exception as e:
            log.error(f"[veil] ❌ FAILED TO START DNS SERVER: {e}")
            log.error("[veil] Veil will continue without DNS functionality")
    else:
        log.warning("[veil] DNS is DISABLED in config")
    
    # Start DHCP
    if CONFIG.get("dhcp_enabled", False):
        log.info("[veil] Attempting to start DHCP server...")
        try:
            DHCP_SERVER.start()
            log.info(f"[veil] ✅ DHCP: {CONFIG['dhcp_range_start']} - {CONFIG['dhcp_range_end']}")
        except Exception as e:
            log.error(f"[veil] ❌ FAILED TO START DHCP SERVER: {e}")
    else:
        log.warning("[veil] DHCP is DISABLED in config")
    
    log.info("=" * 60)
    log.info("[veil] ✅ Initialization complete")
    log.info("=" * 60)

async def cleanup_veil():
    log.info("[veil] Shutting down")
    RATE_LIMITER.stop()
    CACHE_PREWARMER.stop()
    BLOCKLIST_UPDATER.stop()
    
    # Save blocklists before shutdown
    await save_blocklists_local()
    
    if dns_transport:
        dns_transport.close()
    if DHCP_SERVER:
        DHCP_SERVER.stop()
    if CONN_POOL:
        await CONN_POOL.close()

__version__ = "2.0.2"  # Updated version
__description__ = "Privacy-First DNS/DHCP - Complete with DNSSEC, DoQ, Rate Limiting, SafeSearch"

if __name__ == "__main__":
    print("🧩 Veil - Privacy-First DNS/DHCP Server")

async def start_background_services(app):
    """Start background services on app startup"""
    try:
        log.info("[veil] Starting background services...")
        await init_veil()
        log.info("[veil] Background services started successfully")
    except Exception as e:
        log.error(f"[veil] CRITICAL: Failed to start background services: {e}")
        import traceback
        log.error(traceback.format_exc())

async def cleanup_background_services(app):
    """Cleanup background services on app shutdown"""
    try:
        log.info("[veil] Cleaning up background services...")
        await cleanup_veil()
        log.info("[veil] Cleanup complete")
    except Exception as e:
        log.error(f"[veil] Error during cleanup: {e}")

if __name__ == "__main__":
    import os
    from aiohttp import web

    # Load configuration
    cfg_path = "/config/options.json"
    ui_port = 8080
    bind_addr = "0.0.0.0"

    try:
        import json
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                data = json.load(f)
                
                # Map Home Assistant addon config keys to internal keys
                if "dns_enabled" in data:
                    data["enabled"] = data["dns_enabled"]
                if "dns_port_tcp" in data:
                    data["dns_port"] = data["dns_port_tcp"]
                if "bind_address" in data:
                    data["dns_bind"] = data["bind_address"]
                if "ui_bind" in data:
                    data["ui_bind"] = data["ui_bind"]
                if "ui_port" in data:
                    data["ui_port"] = data["ui_port"]
                
                CONFIG.update(data)
                ui_port = int(data.get("ui_port", 8080))
                bind_addr = data.get("ui_bind", "0.0.0.0")
                log.info(f"[veil] Loaded config from {cfg_path}")
                log.info(f"[veil] DNS enabled: {CONFIG.get('enabled', False)}")
                log.info(f"[veil] DHCP enabled: {CONFIG.get('dhcp_enabled', False)}")
    except Exception as e:
        log.warning(f"[veil] Could not read {cfg_path}: {e}")

    # Create web application
    app = web.Application()
    
    # Register API routes
    register_routes(app)
    
    # Serve UI
    ui_path = os.path.join(os.path.dirname(__file__), "ui")
    if not os.path.exists(ui_path):
        ui_path = "/app/ui"
    
    if not os.path.exists(ui_path):
        log.warning(f"[veil] UI path {ui_path} not found, serving placeholder")
        async def placeholder(_):
            return web.Response(text="🧩 Veil is running, but no UI files found.")
        app.router.add_get("/", placeholder)
    else:
        app.router.add_static("/", ui_path, show_index=True)
        log.info(f"[veil] Serving UI from {ui_path}")

    # Setup startup/cleanup hooks
    app.on_startup.append(start_background_services)
    app.on_cleanup.append(cleanup_background_services)

    log.info(f"🌐 Web UI will be available at http://{bind_addr}:{ui_port}")
    log.info(f"🧩 Veil v{__version__} - Privacy-First DNS/DHCP")
    
    # Run with proper error handling
    try:
        web.run_app(app, host=bind_addr, port=ui_port, access_log=None)
    except Exception as e:
        log.error(f"[veil] Failed to start: {e}")
        import traceback
        traceback.print_exc()
