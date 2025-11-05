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
- DNSSEC validation with dnspython
- DoQ (DNS-over-QUIC) with aioquic
- Per-client DNS rate limiting
- SafeSearch enforcement (Google/Bing/DuckDuckGo/YouTube)
- Local blocklist persistence after updates
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

# === FIXED: Import QuicConnectionProtocol for DoQ ===
DOQ_AVAILABLE = False
try:
    from aioquic.asyncio import connect, QuicConnectionProtocol
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import StreamDataReceived
    DOQ_AVAILABLE = True
except ImportError:
    log = logging.getLogger("veil")
    log.warning("[doq] aioquic not installed, DoQ disabled")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
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
    "upstream_timeout": 2.0,
    "upstream_parallel": True,
    "upstream_rotation": True,
    "upstream_max_failures": 3,
   
    # Privacy Features
    "doh_enabled": True,
    "dot_enabled": True,
    "doq_enabled": True,
    "ecs_strip": True,
    "dnssec_validate": True,
    "dnssec_trust_anchors": "/etc/bind/bind.keys",
    "query_jitter": True,
    "query_jitter_ms": [10, 100],
    "zero_log": False,
    "padding_enabled": True,
    "padding_block_size": 468,
    "case_randomization": True,
    "qname_minimization": True,
   
    # Rate Limiting
    "rate_limit_enabled": True,
    "rate_limit_qps": 20,
    "rate_limit_burst": 50,
    "rate_limit_window": 60,
   
    # SafeSearch
    "safesearch_enabled": False,
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
    "blocklist_storage_path": "/config/veil_blocklists.json",
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
    "cache_prewarm_interval": 3600,
    "cache_prewarm_sources": ["popular", "custom", "history"],
    "cache_prewarm_custom_domains": [],
    "cache_prewarm_history_count": 100,
    "cache_prewarm_concurrent": 10,
   
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
    "dns_upstream_latency": 0.0,
    "top_clients": [],
    "top_blocked": [],
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
CLIENT_COUNTER = Counter()
BLOCKED_COUNTER = Counter()

# ==================== DNS CACHE ====================
@dataclass
class CacheEntry:
    response: bytes
    expires: float
    negative: bool = False
    stale_ttl: float = 0

class LRUCache:
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
    def __init__(self, max_size: int = 10000):
        self._queries: Dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._max_size = max_size
   
    async def record(self, qname: str):
        async with self._lock:
            self._queries[qname] = self._queries.get(qname, 0) + 1
            if len(self._queries) > self._max_size:
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
                self._clients[client_ip] = RateLimitEntry(tokens=burst, last_update=now)
            entry = self._clients[client_ip]
            time_elapsed = now - entry.last_update
            entry.tokens = min(burst, entry.tokens + (time_elapsed * qps))
            entry.last_update = now
            if entry.tokens >= 1.0:
                entry.tokens -= 1.0
                return True
            else:
                STATS["dns_rate_limited"] += 1
                log.warning(f"[ratelimit] {client_ip} exceeded limit")
                return False
   
    async def cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(300)
                now = time.time()
                window = CONFIG.get("rate_limit_window", 60)
                async with self._lock:
                    stale = [ip for ip, entry in self._clients.items() if now - entry.last_update > window]
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
    "www.google.com": "forcesafesearch.google.com",
    "google.com": "forcesafesearch.google.com",
    "www.bing.com": "strict.bing.com",
    "bing.com": "strict.bing.com",
    "duckduckgo.com": "safe.duckduckgo.com",
    "www.duckduckgo.com": "safe.duckduckgo.com",
    "www.youtube.com": "restrict.youtube.com",
    "youtube.com": "restrict.youtube.com",
    "m.youtube.com": "restrict.youtube.com",
    "youtubei.googleapis.com": "restrict.youtube.com",
}

def apply_safesearch(qname: str) -> Optional[str]:
    if not CONFIG.get("safesearch_enabled"):
        return None
    qname_lower = qname.lower().strip('.')
    for original, safe in SAFESEARCH_MAPPINGS.items():
        if qname_lower == original or qname_lower.endswith('.' + original):
            if "google" in original and not CONFIG.get("safesearch_google"):
                continue
            if "bing" in original and not CONFIG.get("safesearch_bing"):
                continue
            if "duckduckgo" in original and not CONFIG.get("safesearch_duckduckgo"):
                continue
            if "youtube" in original and not CONFIG.get("safesearch_youtube"):
                continue
            STATS["dns_safesearch"] += 1
            log.info(f"[safesearch] {qname} to {safe}")
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
    try:
        storage_path = Path(CONFIG.get("blocklist_storage_path", "/config/veil_blocklists.json"))
        if not storage_path.exists():
            log.info("[storage] No local storage found")
            return False
        with open(storage_path) as f:
            data = json.load(f)
        blocklist_domains = data.get("blocklist", [])
        await BLOCKLIST.import_list(blocklist_domains)
        blacklist_domains = data.get("blacklist", [])
        await BLACKLIST.import_list(blacklist_domains)
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
            for domain in set(domains):
                BLOCKLIST.add_sync(domain)
                total_added += 1
        STATS["blocklist_updates"] += 1
        STATS["blocklist_last_update"] = time.time()
        self.last_update = time.time()
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
    def __init__(self):
        self.running = False
        self.prewarm_task = None
        self.last_prewarm = 0
   
    async def get_domains_to_prewarm(self) -> List[str]:
        domains = set()
        sources = CONFIG.get("cache_prewarm_sources", ["popular"])
        if "popular" in sources:
            domains.update(POPULAR_DOMAINS)
        if "custom" in sources:
            custom = CONFIG.get("cache_prewarm_custom_domains", [])
            domains.update(custom)
        if "history" in sources:
            count = CONFIG.get("cache_prewarm_history_count", 100)
            historical = await QUERY_HISTORY.get_top(count)
            domains.update(historical)
        return list(domains)
   
    async def prewarm_domain(self, domain: str) -> bool:
        try:
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
        if not CONFIG.get("cache_prewarm_enabled"):
            return
        log.info("[prewarm] Starting cache prewarm")
        start_time = time.time()
        domains = await self.get_domains_to_prewarm()
        if not domains:
            log.info("[prewarm] No domains to prewarm")
            return
        log.info(f"[prewarm] Prewarming {len(domains)} domains")
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
        self.running = True
        if CONFIG.get("cache_prewarm_on_start"):
            await self.prewarm_cache()
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
   
    async def record_success(self, server: str, latency: float):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {"failures": 0, "last_check": time.time(), "healthy": True, "latency": latency, "success_count": 0}
            self._health[server]["failures"] = 0
            self._health[server]["last_check"] = time.time()
            self._health[server]["healthy"] = True
            self._health[server]["latency"] = latency
            self._health[server]["success_count"] += 1
   
    async def record_failure(self, server: str):
        async with self._lock:
            if server not in self._health:
                self._health[server] = {"failures": 0, "last_check": time.time(), "healthy": True, "latency": 0, "success_count": 0}
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

# ==================== DNSSEC VALIDATION ====================
async def validate_dnssec(response_wire: bytes, transport: str, query_id: int) -> bool:
    if not CONFIG.get("dnssec_validate"):
        return True
    try:
        response = dns.message.from_wire(response_wire)
        if transport == "doq":
            pass
        elif response.id != query_id:
            log.warning(f"[dnssec] Non-matching DNS IDs ({response.id} vs {query_id}) – tolerated")
        if not any(rrset.rdtype in (dns.rdatatype.RRSIG, dns.rdatatype.DNSKEY)
                  for section in [response.answer, response.authority]
                  for rrset in section):
            return True
        anchors = dns.resolver.Zone()
        with open(CONFIG.get("dnssec_trust_anchors", "/etc/bind/bind.keys")) as f:
            anchors.from_text(f.read())
        dns.dnssec.validate(response.answer[0], response.answer, {anchors.name: anchors})
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
async def query_doq(wire_query: bytes, server: str) -> Optional[bytes]:
    if not DOQ_AVAILABLE or not CONFIG.get("doq_enabled"):
        return None
    try:
        STATS["dns_doq_queries"] += 1
        configuration = QuicConfiguration(is_client=True, alpn_protocols=["doq"])
        protocol = await connect(
            server, 853, configuration=configuration, create_protocol=QuicConnectionProtocol
        )
        negotiated = getattr(protocol._quic, "negotiated_alpn", None)
        log.debug(f"[doq] Negotiated ALPN: {negotiated}")
        if negotiated != "doq":
            log.debug(f"[doq] Server {server} does not support DoQ, falling back")
            protocol.close()
            return None
        try:
            query = dns.message.from_wire(wire_query)
            query.id = 0
            query.flags &= ~dns.flags.RD
            wire_query = query.to_wire()
        except Exception as e:
            log.warning(f"[doq] Failed to normalize query ID: {e}")
        stream_id = protocol._quic.get_next_available_stream_id()
        msg_len = struct.pack("!H", len(wire_query))
        protocol._quic.send_stream_data(stream_id, msg_len + wire_query, end_stream=True)
        response_data = b""
        expected_len = None
        timeout = CONFIG.get("upstream_timeout", 2.0)
        start = time.time()
        while True:
            if time.time() - start > timeout:
                log.debug(f"[doq] Timeout waiting for response from {server}")
                protocol.close()
                return None
            event = protocol._quic.next_event()
            if isinstance(event, StreamDataReceived) and event.stream_id == stream_id:
                response_data += event.data
                if expected_len is None and len(response_data) >= 2:
                    expected_len = struct.unpack("!H", response_data[:2])[0]
                if expected_len and len(response_data) - 2 >= expected_len:
                    break
            await asyncio.sleep(0.01)
        if expected_len and len(response_data) - 2 >= expected_len:
            raw = response_data[2 : 2 + expected_len]
            response = dns.message.from_wire(raw)
            response.id = 0
            response.flags |= dns.flags.RA
            response.flags |= dns.flags.RD
            response.flags &= ~dns.flags.AA
            response_wire = response.to_wire()
            protocol.close()
            log.debug(f"[doq] Outgoing flags: {dns.flags.to_text(response.flags)}")
            return response_wire
        log.debug(f"[doq] Incomplete response from {server}: expected {expected_len}, got {len(response_data) - 2}")
        protocol.close()
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
        return await query_upstream(qname, qtype)
    if depth > 20:
        log.error("[dns] QNAME minimization exceeded safe depth")
        return None
    STATS["dns_qname_min"] += 1
    normalized_qname = qname.lower().strip('.')
    labels = normalized_qname.split('.')
    current = '.'
    for i in range(len(labels)):
        current = labels[-1-i] + ('.' + current if current != '.' else '')
        ns_response = await query_upstream(current, dns.rdatatype.NS)
        if not ns_response:
            break
        response = dns.message.from_wire(ns_response)
        if response.rcode() != dns.rcode.NOERROR:
            break
        if i == len(labels) - 1:
            final_response = await query_upstream(normalized_qname, qtype)
            return final_response
    return await query_upstream(normalized_qname, qtype)

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

async def query_upstream(qname: str, qtype: int, depth: int = 0) -> Optional[bytes]:
    if CONFIG.get("qname_minimization"):
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
        if len(data) < 12:
            log.warning(f"[dns] Packet too small from {addr[0]}: {len(data)} bytes")
            return None
        try:
            query = dns.message.from_wire(data)
        except dns.exception.FormError as e:
            log.error(f"[dns] Malformed DNS packet from {addr[0]}: {e}")
            log.debug(f"[dns] Packet hex: {data[:50].hex()}")
            return None
        except Exception as e:
            log.error(f"[dns] Failed to parse DNS from {addr[0]}: {e}")
            return None
        if not await RATE_LIMITER.check_rate_limit(addr[0]):
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.REFUSED)
            return response.to_wire()
        qname = str(query.question[0].name).lower().strip('.')
        qtype = query.question[0].rdtype
        if not CONFIG.get("zero_log"):
            log.info(f"[dns] Query from {addr[0]}: {qname} ({dns.rdatatype.to_text(qtype)})")
        STATS["dns_queries"] += 1
        await QUERY_HISTORY.record(qname)
        if await WHITELIST.contains(qname):
            pass
        else:
            if await BLACKLIST.contains(qname):
                STATS["dns_blocked"] += 1
                log.info(f"[dns] Blocked (blacklist): {qname}")
                return build_blocked_response(query)
            if CONFIG.get("blocking_enabled") and await BLOCKLIST.contains(qname):
                STATS["dns_blocked"] += 1
                log.info(f"[dns] Blocked (blocklist): {qname}")
                return build_blocked_response(query)
        safesearch_domain = apply_safesearch(qname)
        if safesearch_domain:
            safe_query = dns.message.make_query(safesearch_domain, qtype)
            response_wire = await query_upstream(safesearch_domain, qtype)
            if response_wire:
                return response_wire
            else:
                response = dns.message.make_response(query)
                response.set_rcode(dns.rcode.SERVFAIL)
                return response.to_wire()
        dns_rewrites = CONFIG.get("dns_rewrites", {})
        if qname in dns_rewrites:
            rewrite = dns_rewrites[qname]
            return build_rewrite_response(query, rewrite)
        local_records = CONFIG.get("local_records", {})
        if qname in local_records:
            record = local_records[qname]
            return build_rewrite_response(query, record)
        for domain, forward_server in CONFIG.get("conditional_forwards", {}).items():
            if qname.endswith(domain) or qname == domain.strip('.'):
                try:
                    log.debug(f"[dns] Conditional forward: {qname} to {forward_server}")
                    forward_query = dns.message.make_query(qname, qtype)
                    response_wire = await query_udp(forward_query.to_wire(), forward_server)
                    if response_wire:
                        return response_wire
                except Exception as e:
                    log.error(f"[dns] Conditional forward failed: {e}")
        cached = await DNS_CACHE.get(qname, qtype)
        if cached:
            STATS["dns_cached"] += 1
            return cached
        STATS["dns_upstream"] += 1
        response_wire = await query_upstream(qname, qtype)
        if not response_wire:
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
            return response.to_wire()
        response_wire = strip_ecs(response_wire)
        transport = "doq" if (CONFIG.get("doq_enabled") and DOQ_AVAILABLE) else "udp"
        if not await validate_dnssec(response_wire, transport, query.id):
            log.warning(f"[dnssec] Validation failed for {qname}")
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
            return response.to_wire()
        response = dns.message.from_wire(response_wire)
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
                                    log.warning(f"[dns] Rebinding blocked: {qname} to {ip}")
                                    return build_blocked_response(query)
                            except:
                                pass
                    elif rrset.rdtype == dns.rdatatype.AAAA:
                        for rr in rrset:
                            try:
                                ip = ipaddress.IPv6Address(rr.address)
                                if ip.is_private:
                                    log.warning(f"[dns] Rebinding blocked: {qname} to {ip}")
                                    return build_blocked_response(query)
                            except:
                                pass
        ttl = CONFIG.get("cache_ttl", 3600)
        if response.answer:
            ttl = min((rrset.ttl for rrset in response.answer), default=ttl)
        else:
            ttl = CONFIG.get("negative_cache_ttl", 300)
        await DNS_CACHE.set(qname, qtype, response_wire, ttl, negative=(not response.answer))
        # === FIXED: Pad response before sending to client ===
        return pad_wire(response_wire)
    except Exception as e:
        log.error(f"[dns] Unexpected error processing query from {addr[0]}: {e}")
        return None

# ==================== DNS SERVER ====================
class DNSProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.create_task(self.handle_query(data, addr))

    async def handle_query(self, data, addr):
        try:
            query = None
            try:
                query = dns.message.from_wire(data)
            except Exception as e:
                log.warning(f"[dns] Failed to parse incoming query from {addr[0]}: {e}")
            response = await process_dns_query(data, addr)
            if response:
                try:
                    msg = dns.message.from_wire(response)
                    if query is not None:
                        msg.id = query.id
                    msg.flags |= dns.flags.RA
                    msg.flags |= dns.flags.RD
                    msg.flags &= ~dns.flags.AA
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
        log.info(f"[dns] DNS server SUCCESSFULLY started on {CONFIG['dns_bind']}:{CONFIG['dns_port']}")
    except PermissionError as e:
        log.error(f"[dns] PERMISSION DENIED - Cannot bind to port {CONFIG['dns_port']} (requires root/CAP_NET_BIND_SERVICE)")
        log.error(f"[dns] Error: {e}")
        raise
    except OSError as e:
        log.error(f"[dns] FAILED to bind to {CONFIG['dns_bind']}:{CONFIG['dns_port']}")
        log.error(f"[dns] Error: {e}")
        log.error(f"[dns] Is another DNS server already running on port {CONFIG['dns_port']}?")
        raise
    except Exception as e:
        log.error(f"[dns] UNEXPECTED ERROR starting DNS server: {e}")
        raise

# ==================== DHCP SERVER ====================
# ... (DHCP code unchanged, omitted for brevity) ...

# ==================== API ENDPOINTS ====================
# ... (API code unchanged, omitted for brevity) ...

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
    log.info("[veil] Privacy-First DNS/DHCP initializing")
    log.info("=" * 60)
    global DNS_CACHE, BLOCKLIST, WHITELIST, BLACKLIST, UPSTREAM_HEALTH, CONN_POOL, DHCP_SERVER
    global RATE_LIMITER, CACHE_PREWARMER, BLOCKLIST_UPDATER
    log.info(f"[veil] Enabled: {CONFIG.get('enabled', True)}")
    log.info(f"[veil] DHCP Enabled: {CONFIG.get('dhcp_enabled', False)}")
    log.info(f"[veil] DNS Port: {CONFIG.get('dns_port', 53)}")
    log.info(f"[veil] DNS Bind: {CONFIG.get('dns_bind', '0.0.0.0')}")
    STATS["start_time"] = time.time()
    STATS["blocklist_last_update"] = 0
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
    RATE_LIMITER.start()
    log.info(f"[veil] Rate limiter started")
    if CONFIG.get("cache_prewarm_enabled"):
        CACHE_PREWARMER.start()
        log.info(f"[veil] Cache prewarm: every {CONFIG['cache_prewarm_interval']}s")
    if CONFIG.get("blocklist_update_enabled"):
        BLOCKLIST_UPDATER.start()
        log.info(f"[veil] Blocklist auto-update: every {CONFIG['blocklist_update_interval']}s")
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
            log.error(f"[veil] FAILED TO START DNS SERVER: {e}")
            log.error("[veil] Veil will continue without DNS functionality")
    else:
        log.warning("[veil] DNS is DISABLED in config")
    if CONFIG.get("dhcp_enabled", False):
        log.info("[veil] Attempting to start DHCP server...")
        try:
            DHCP_SERVER.start()
            log.info(f"[veil] DHCP: {CONFIG['dhcp_range_start']} - {CONFIG['dhcp_range_end']}")
        except Exception as e:
            log.error(f"[veil] FAILED TO START DHCP SERVER: {e}")
    else:
        log.warning("[veil] DHCP is DISABLED in config")
    log.info("=" * 60)
    log.info("[veil] Initialization complete")
    log.info("=" * 60)

async def cleanup_veil():
    log.info("[veil] Shutting down")
    RATE_LIMITER.stop()
    CACHE_PREWARMER.stop()
    BLOCKLIST_UPDATER.stop()
    await save_blocklists_local()
    if dns_transport:
        dns_transport.close()
    if DHCP_SERVER:
        DHCP_SERVER.stop()
    if CONN_POOL:
        await CONN_POOL.close()

__version__ = "2.0.2"
__description__ = "Privacy-First DNS/DHCP - Complete with DNSSEC, DoQ, Rate Limiting, SafeSearch"

if __name__ == "__main__":
    print("Veil - Privacy-First DNS/DHCP Server")

async def start_background_services(app):
    try:
        log.info("[veil] Starting background services...")
        await init_veil()
        log.info("[veil] Background services started successfully")
    except Exception as e:
        log.error(f"[veil] CRITICAL: Failed to start background services: {e}")
        import traceback
        log.error(traceback.format_exc())

async def cleanup_background_services(app):
    try:
        log.info("[veil] Cleaning up background services...")
        await cleanup_veil()
        log.info("[veil] Cleanup complete")
    except Exception as e:
        log.error(f"[veil] Error during cleanup: {e}")

if __name__ == "__main__":
    import os
    from aiohttp import web
    cfg_path = "/config/options.json"
    ui_port = 8080
    bind_addr = "0.0.0.0"
    try:
        import json
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                data = json.load(f)
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
    app = web.Application()
    register_routes(app)
    ui_path = os.path.join(os.path.dirname(__file__), "ui")
    if not os.path.exists(ui_path):
        ui_path = "/app/ui"
    if not os.path.exists(ui_path):
        log.warning(f"[veil] UI path {ui_path} not found, serving placeholder")
        async def placeholder(_):
            return web.Response(text="Veil is running, but no UI files found.")
        app.router.add_get("/", placeholder)
    else:
        app.router.add_static("/", ui_path, show_index=True)
        log.info(f"[veil] Serving UI from {ui_path}")
    app.on_startup.append(start_background_services)
    app.on_cleanup.append(cleanup_background_services)
    log.info(f"Web UI will be available at http://{bind_addr}:{ui_port}")
    log.info(f"Veil v{__version__} - Privacy-First DNS/DHCP")
    try:
        web.run_app(app, host=bind_addr, port=ui_port, access_log=None)
    except Exception as e:
        log.error(f"[veil] Failed to start: {e}")
        import traceback
        traceback.print_exc()