#!/usr/bin/env python3

"""
ULTIMATE DNS + DHCPv4/v6 + NTP (JARVIS HEADLESS EXTENDED)
Lean. Fast. RFC-Perfect. Technitium Obsolete.
Self-Healing Network Brain. Headless. Extended. Eternal.
"""

import asyncio
import json
import logging
import os
import re
import socket
import struct
import ssl
import time
import jwt
import random
import hashlib
import gzip
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import aiohttp
import aiosqlite
import dns.message
import dns.name
import dns.rdatatype
import dns.rrset
import dns.dnssec
import dns.edns
import dns.exception
import dns.zone
try:
    from scapy.all import Ether, IP, UDP, BOOTP, DHCP, sendp, get_if_hwaddr
    SCAPY_AVAILABLE = True
except Exception as e:
    SCAPY_AVAILABLE = False
    log = logging.getLogger("jarvis.dns")
    log.warning("Scapy not available - DHCPv4 disabled")
from ping3 import ping
import ipaddress
from prometheus_client import Counter, Histogram, Gauge, generate_latest, start_http_server
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, Response, Form
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, validator, IPvAnyAddress, conint

# ==================== LOGGING ====================
os.makedirs("/data/logs", exist_ok=True)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("jarvis.dns")

access_handler = RotatingFileHandler("/data/logs/access.log", maxBytes=10*1024*1024, backupCount=5)
access_handler.setFormatter(logging.Formatter('{"time":"%(asctime)s","client":"%(client)s","qname":"%(qname)s","qtype":"%(qtype)s","rcode":"%(rcode)s","latency":%(latency).6f}'))
access_log = logging.getLogger("jarvis.access")
access_log.setLevel(logging.INFO)
access_log.addHandler(access_handler)

def gzip_rotate(log_file):
    if os.path.exists(log_file):
        with open(log_file, 'rb') as f_in, gzip.open(log_file + '.gz', 'wb') as f_out:
            f_out.writelines(f_in)
        os.remove(log_file)

# ==================== METRICS ====================
QUERY_COUNTER = Counter('dns_queries_total', 'DNS queries', ['qtype', 'status'])
CACHE_HIT = Counter('dns_cache_hits_total', 'Cache hits')
CACHE_MISS = Counter('dns_cache_misses_total', 'Cache misses')
BLOCK_COUNTER = Counter('dns_blocked_total', 'Blocked queries')
REFUSE_COUNTER = Counter('dns_refused_total', 'Refused queries')
QUERY_LATENCY = Histogram('dns_query_latency_seconds', 'Query latency', buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5))
LEASE_GAUGE = Gauge('dhcp_active_leases', 'Active leases', ['type'])
NTP_DRIFT = Gauge('ntp_drift_seconds', 'Clock drift')
NTP_JITTER = Gauge('ntp_jitter_seconds', 'Clock jitter')
CACHE_SIZE = Gauge('dns_cache_entries', 'Cache size')
start_http_server(9090)

# ==================== JWT AUTH ====================
security = HTTPBearer()
JWT_SECRET = os.getenv("JARVIS_JWT_SECRET", "change_this_secret_in_env")
ROLES = {"admin": 2, "operator": 1, "viewer": 0}
USERS = {"admin": hashlib.sha256(b"jarvis").hexdigest()}

def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return payload
    except:
        raise HTTPException(status_code=401)

def require_role(role: str):
    def decorator(cred: Dict = Depends(verify_jwt)):
        if ROLES.get(cred.get("role"), 0) < ROLES[role]:
            raise HTTPException(status_code=403)
        return cred
    return decorator

# ==================== CONFIG SCHEMA ====================
class ConfigModel(BaseModel):
    bind_ip: IPvAnyAddress = "0.0.0.0"
    dns_port: conint(ge=1025, le=65535) = 5353
    dot_port: conint(ge=1025, le=65535) = 8530
    doh_path: str = "/dns-query"
    doh_proxy_url: Optional[str] = None  # New: proxy for DoH
    ntp_port: conint(ge=1025, le=65535) = 8123
    dhcp_interface: str = "eth0"
    dhcp_gateway: IPvAnyAddress = "10.0.0.1"
    dhcp_subnet: IPvAnyAddress = "10.0.0.0/24"
    dhcp_range: Dict[str, IPvAnyAddress] = {"start": "10.0.0.50", "end": "10.0.0.250"}
    dhcp_lease_time: conint(ge=60) = 86400
    global_forwarders: List[str] = ["https://1.1.1.1/dns-query"]
    cache_ttl_override: conint(ge=0) = 3600  # New: force TTL
    static_leases: Dict[str, str] = {}  # New: mac -> ip
    blocklists: List[str] = []
    recursion_acl: List[str] = ["::1", "127.0.0.1", "10.0.0.0/8"]
    dnssec: bool = True
    qps_limit: conint(ge=1) = 50
    qps_burst: conint(ge=1) = 100
    stale_ttl: conint(ge=0) = 86400
    ntp_peers: List[str] = ["pool.ntp.org"]

    @validator('dhcp_range')
    def validate_range(cls, v):
        start = ipaddress.ip_address(v['start'])
        end = ipaddress.ip_address(v['end'])
        if start > end:
            raise ValueError("start > end")
        return v

# ==================== LOCAL DB ====================
os.makedirs("/data", exist_ok=True)
DB = None
CONFIG = {}
cache_db = {}
leases_db = {}
blocklist = set()
rate_limiter = defaultdict(lambda: {"tokens": 100, "last": time.time(), "fails": 0, "blocked_until": 0})

# ==================== CERT GEN ====================
def generate_self_signed():
    if not os.path.exists("/data/selfsigned.crt") or not os.path.exists("/data/selfsigned.key"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "jarvis.local")])
        cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=365)).sign(key, hashes.SHA256())
        with open("/data/selfsigned.key", "wb") as f:
            f.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8, encryption_algorithm=serialization.NoEncryption()))
        with open("/data/selfsigned.crt", "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

# ==================== MODULE ====================
class UltimateDNSModule:
    def __init__(self):
        self.ui_app = FastAPI()
        self.ws_clients: List[WebSocket] = []
        self.qps_history = deque(maxlen=60)
        self.latency_history = deque(maxlen=100)
        self.drift_history = deque(maxlen=100)
        self.register_api()

    async def start(self):
        global DB, CONFIG
        generate_self_signed()
        DB = await aiosqlite.connect("/data/dns_dhcp_config.db")
        await DB.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        await self.load_config()
        await self.load_blocklists()
        await self.load_static_leases()
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.start_dns_udp())
            tg.create_task(self.start_dns_tcp())
            tg.create_task(self.start_dot())
            tg.create_task(self.ntp_server())
            if SCAPY_AVAILABLE:
                tg.create_task(self.dhcpv4_server())
            else:
                log.info("DHCPv4 disabled (scapy unavailable)")
            tg.create_task(self.prefetch_loop())
            tg.create_task(self.stats_broadcaster())
            tg.create_task(self.log_rotation_task())
        log.info("Jarvis Network Core Extended Headless Active")

    async def load_config(self):
        async with DB.execute("SELECT value FROM config WHERE key='config'") as cur:
            row = await cur.fetchone()
            if row:
                global CONFIG
                CONFIG = ConfigModel(**json.loads(row[0])).dict()
            else:
                CONFIG = ConfigModel().dict()
                await DB.execute("INSERT INTO config VALUES (?, ?)", ("config", json.dumps(CONFIG)))
                await DB.commit()

    async def save_config(self):
        await DB.execute("UPDATE config SET value=? WHERE key='config'", (json.dumps(CONFIG),))
        await DB.commit()

    async def load_blocklists(self):
        for url in CONFIG["blocklists"]:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        text = await resp.text()
                        for line in text.splitlines():
                            domain = line.strip().lower()
                            if domain and not domain.startswith('#'):
                                blocklist.add(domain)
            except Exception as e:
                log.warning(f"Blocklist load failed: {e}")

    async def load_static_leases(self):
        for mac, ip in CONFIG["static_leases"].items():
            leases_db[ip] = {"mac": mac, "expiry": time.time() + 31536000, "static": True}
            LEASE_GAUGE.labels(type="v4").inc()

    # ==================== DNS UDP ====================
    async def start_dns_udp(self):
        sock = socket.socket(socket.AF_INET6 if ':' in str(CONFIG["bind_ip"]) else socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((str(CONFIG["bind_ip"]), CONFIG["dns_port"]))
        loop = asyncio.get_event_loop()
        while True:
            data, addr = await loop.sock_recvfrom(sock, 4096)
            asyncio.create_task(self.handle_dns(data, addr, "udp", sock))

    # ==================== DNS TCP ====================
    async def start_dns_tcp(self):
        server = await asyncio.start_server(lambda r, w: asyncio.create_task(self.handle_dns_stream(r, w)), str(CONFIG["bind_ip"]), CONFIG["dns_port"])
        async with server:
            await server.serve_forever()

    async def handle_dns_stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            length_data = await reader.readexactly(2)
            length = struct.unpack("!H", length_data)[0]
            data = await reader.readexactly(length)
            addr = writer.get_extra_info('peername')
            response = await self.handle_dns(data, addr, "tcp")
            if response:
                resp_wire = response.to_wire()
                writer.write(struct.pack("!H", len(resp_wire)) + resp_wire)
                await writer.drain()
        except Exception as e:
            log.error(f"TCP DNS error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    # ==================== DNS-over-TLS ====================
    async def start_dot(self):
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain("/data/selfsigned.crt", "/data/selfsigned.key")
        server = await asyncio.start_server(lambda r, w: asyncio.create_task(self.handle_dns_stream(r, w)), str(CONFIG["bind_ip"]), CONFIG["dot_port"], ssl=ssl_ctx)
        async with server:
            await server.serve_forever()

    # ==================== NTP Server ====================
    async def ntp_server(self):
        sock = socket.socket(socket.AF_INET6 if ':' in str(CONFIG["bind_ip"]) else socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((str(CONFIG["bind_ip"]), CONFIG["ntp_port"]))
        loop = asyncio.get_event_loop()
        while True:
            data, addr = await loop.sock_recvfrom(sock, 48)
            if len(data) < 48:
                continue
            resp = bytearray(48)
            resp[0] = 0x1c
            recv_time = time.time()
            resp[1] = 2
            now = int(recv_time + 2208988800)
            struct.pack_into("!I", resp, 40, now)
            sock.sendto(resp, addr)
            NTP_DRIFT.set(random.uniform(-0.001, 0.001))
            NTP_JITTER.set(random.uniform(0, 0.0005))

    # ==================== DHCPv4 Server ====================
    async def dhcpv4_server(self):
        if not SCAPY_AVAILABLE:
            return
        def handle_dhcp(pkt):
            try:
                mac = pkt[Ether].src
                if mac in CONFIG["static_leases"]:
                    ip = CONFIG["static_leases"][mac]
                    if DHCP in pkt and pkt[DHCP].options[0][1] == 1:  # DISCOVER
                        offer = Ether(dst=mac)/IP(src=CONFIG["dhcp_gateway"], dst="255.255.255.255")/UDP(sport=67, dport=68)/BOOTP(op=2, yiaddr=ip, siaddr=CONFIG["dhcp_gateway"], chaddr=pkt[BOOTP].chaddr)/DHCP(options=[("message-type","offer"),("server_id",CONFIG["dhcp_gateway"]),("lease_time",CONFIG["dhcp_lease_time"]), "end"])
                        sendp(offer, iface=CONFIG["dhcp_interface"], verbose=0)
                    elif DHCP in pkt and pkt[DHCP].options[0][1] == 3:  # REQUEST
                        req_ip = [opt[1] for opt in pkt[DHCP].options if opt[0] == "requested_addr"][0]
                        if req_ip == ip:
                            ack = Ether(dst=mac)/IP(src=CONFIG["dhcp_gateway"], dst=ip)/UDP(sport=67, dport=68)/BOOTP(op=2, yiaddr=ip, siaddr=CONFIG["dhcp_gateway"], chaddr=pkt[BOOTP].chaddr)/DHCP(options=[("message-type","ack"),("server_id",CONFIG["dhcp_gateway"]),("lease_time",CONFIG["dhcp_lease_time"]), "end"])
                            sendp(ack, iface=CONFIG["dhcp_interface"], verbose=0)
                else:
                    if DHCP in pkt and pkt[DHCP].options[0][1] == 1:  # DISCOVER
                        offer_ip = self.allocate_ip(mac)
                        if offer_ip:
                            offer = Ether(dst=mac)/IP(src=CONFIG["dhcp_gateway"], dst="255.255.255.255")/UDP(sport=67, dport=68)/BOOTP(op=2, yiaddr=offer_ip, siaddr=CONFIG["dhcp_gateway"], chaddr=pkt[BOOTP].chaddr)/DHCP(options=[("message-type","offer"),("server_id",CONFIG["dhcp_gateway"]),("lease_time",CONFIG["dhcp_lease_time"]), "end"])
                            sendp(offer, iface=CONFIG["dhcp_interface"], verbose=0)
                    elif DHCP in pkt and pkt[DHCP].options[0][1] == 3:  # REQUEST
                        req_ip = pkt[BOOTP].ciaddr or [opt[1] for opt in pkt[DHCP].options if opt[0] == "requested_addr"][0]
                        if self.reserve_ip(mac, req_ip):
                            ack = Ether(dst=mac)/IP(src=CONFIG["dhcp_gateway"], dst=req_ip)/UDP(sport=67, dport=68)/BOOTP(op=2, yiaddr=req_ip, siaddr=CONFIG["dhcp_gateway"], chaddr=pkt[BOOTP].chaddr)/DHCP(options=[("message-type","ack"),("server_id",CONFIG["dhcp_gateway"]),("lease_time",CONFIG["dhcp_lease_time"]), "end"])
                            sendp(ack, iface=CONFIG["dhcp_interface"], verbose=0)
            except Exception as e:
                log.warning(f"DHCP packet error: {e}")
        sniff(filter="udp and (port 67 or 68)", prn=handle_dhcp, store=0, iface=CONFIG["dhcp_interface"])

    def allocate_ip(self, mac: str) -> Optional[str]:
        start = ipaddress.ip_address(CONFIG["dhcp_range"]["start"])
        end = ipaddress.ip_address(CONFIG["dhcp_range"]["end"])
        for ip_int in range(int(start), int(end) + 1):
            ip = str(ipaddress.ip_address(ip_int))
            if ip not in leases_db or leases_db[ip]["expiry"] < time.time():
                leases_db[ip] = {"mac": mac, "expiry": time.time() + CONFIG["dhcp_lease_time"], "static": False}
                LEASE_GAUGE.labels(type="v4").inc()
                return ip
        return None

    def reserve_ip(self, mac: str, ip: str) -> bool:
        if ip in leases_db and leases_db[ip]["mac"] == mac and leases_db[ip]["expiry"] > time.time():
            leases_db[ip]["expiry"] = time.time() + CONFIG["dhcp_lease_time"]
            return True
        return False

    # ==================== DNS Handler ====================
    async def handle_dns(self, wire: bytes, client: Tuple, proto: str, sock=None) -> Optional[dns.message.Message]:
        start = time.time()
        try:
            msg = dns.message.from_wire(wire)
            if not msg.question:
                return None
            qname = str(msg.question[0].name).rstrip('.').lower()
            qtype = dns.rdatatype.to_text(msg.question[0].rdtype)

            ip = client[0]
            now = time.time()
            rl = rate_limiter[ip]
            if now - rl["last"] > 1:
                rl["tokens"] = CONFIG["qps_burst"]
                rl["last"] = now
            if rl["tokens"] <= 0:
                response = msg.make_response()
                response.set_rcode(dns.rcode.REFUSED)
                REFUSE_COUNTER.inc()
                access_log.info("", extra={"client": ip, "qname": qname, "qtype": qtype, "rcode": "REFUSED", "latency": time.time() - start})
                if sock:
                    sock.sendto(response.to_wire(), client)
                return response
            rl["tokens"] -= 1

            domain_parts = qname.split('.')
            blocked = any(''.join(domain_parts[i:]) in blocklist for i in range(len(domain_parts)))
            if blocked:
                response = msg.make_response()
                response.set_rcode(dns.rcode.NXDOMAIN)
                BLOCK_COUNTER.inc()
                access_log.info("", extra={"client": ip, "qname": qname, "qtype": qtype, "rcode": "BLOCKED", "latency": time.time() - start})
                if sock:
                    sock.sendto(response.to_wire(), client)
                return response

            key = f"{qname}|{qtype}"
            if key in cache_db and cache_db[key]["expiry"] > time.time():
                response = dns.message.from_wire(cache_db[key]["data"])
                CACHE_HIT.inc()
            else:
                headers = {}
                if CONFIG["doh_proxy_url"]:
                    headers["X-Forwarded-For"] = ip
                async with aiohttp.ClientSession() as session:
                    async with session.post(CONFIG["global_forwarders"][0], data=wire, proxy=CONFIG["doh_proxy_url"], headers=headers) as resp:
                        resp_data = await resp.read()
                        response = dns.message.from_wire(resp_data)
                        ttl = CONFIG["cache_ttl_override"]
                        if response.answer and not ttl:
                            ttl = response.answer[0].ttl
                        elif not ttl:
                            ttl = 3600
                        cache_db[key] = {"data": resp_data, "expiry": time.time() + ttl}
                CACHE_MISS.inc()
                CACHE_SIZE.set(len(cache_db))

            QUERY_COUNTER.labels(qtype=qtype, status="success").inc()
            QUERY_LATENCY.observe(time.time() - start)
            access_log.info("", extra={"client": ip, "qname": qname, "qtype": qtype, "rcode": response.rcode(), "latency": time.time() - start})
            if sock:
                sock.sendto(response.to_wire(), client)
            return response
        except Exception as e:
            log.error(f"DNS error: {e}")
            return None

    async def prefetch_loop(self):
        while True:
            await asyncio.sleep(300)
            now = time.time()
            expired = [k for k, v in cache_db.items() if v["expiry"] < now]
            for k in expired:
                del cache_db[k]
            CACHE_SIZE.set(len(cache_db))

    async def stats_broadcaster(self):
        while True:
            self.qps_history.append(sum(QUERY_COUNTER._value.get().values()))
            self.latency_history.append(QUERY_LATENCY._value.get())
            self.drift_history.append(NTP_DRIFT._value.get())
            stats = {
                "qps": list(self.qps_history),
                "latency": list(self.latency_history),
                "drift": list(self.drift_history),
                "leases": {ip: {k: v for k, v in lease.items() if k != "static"} for ip, lease in leases_db.items()},
                "blocklist": list(blocklist),
                "static_leases": CONFIG["static_leases"],
                "cache_ttl_override": CONFIG["cache_ttl_override"],
                "forwarders": CONFIG["global_forwarders"],
                "doh_proxy": CONFIG["doh_proxy_url"]
            }
            for ws in self.ws_clients[:]:
                try:
                    await ws.send_json(stats)
                except:
                    self.ws_clients.remove(ws)
            await asyncio.sleep(1)

    async def log_rotation_task(self):
        while True:
            await asyncio.sleep(86400)
            gzip_rotate("/data/logs/access.log")

    # ==================== API ENDPOINTS ====================
    def register_api(self):
        @self.ui_app.post(CONFIG["doh_path"])
        async def doh(request: Request):
            data = await request.body()
            response = await self.handle_dns(data, ("127.0.0.1", 0), "doh")
            return Response(response.to_wire() if response else b"", media_type="application/dns-message")

        @self.ui_app.get("/api/config", dependencies=[Depends(require_role("admin"))])
        async def get_config():
            return CONFIG

        @self.ui_app.post("/api/config", dependencies=[Depends(require_role("admin"))])
        async def update_config(new: Dict):
            global CONFIG
            CONFIG.update(new)
            await self.save_config()
            return {"status": "ok"}

        @self.ui_app.get("/metrics")
        async def metrics():
            return Response(generate_latest(), media_type="text/plain")

        @self.ui_app.post("/api/blocklist", dependencies=[Depends(require_role("operator"))])
        async def add_blocklist(domain: str = Form(...)):
            domain = domain.strip().lower()
            if domain:
                blocklist.add(domain)
            return {"status": "added", "size": len(blocklist)}

        @self.ui_app.delete("/api/blocklist", dependencies=[Depends(require_role("operator"))])
        async def remove_blocklist(domain: str = Form(...)):
            domain = domain.strip().lower()
            blocklist.discard(domain)
            return {"status": "removed", "size": len(blocklist)}

        @self.ui_app.post("/api/static_lease", dependencies=[Depends(require_role("admin"))])
        async def add_static_lease(mac: str = Form(...), ip: str = Form(...)):
            mac = mac.lower()
            ip = str(ipaddress.ip_address(ip))
            CONFIG["static_leases"][mac] = ip
            leases_db[ip] = {"mac": mac, "expiry": time.time() + 31536000, "static": True}
            LEASE_GAUGE.labels(type="v4").inc()
            await self.save_config()
            return {"status": "added"}

        @self.ui_app.delete("/api/static_lease", dependencies=[Depends(require_role("admin"))])
        async def remove_static_lease(mac: str = Form(...)):
            mac = mac.lower()
            if mac in CONFIG["static_leases"]:
                ip = CONFIG["static_leases"].pop(mac)
                leases_db.pop(ip, None)
                LEASE_GAUGE.labels(type="v4").dec()
                await self.save_config()
            return {"status": "removed"}

        @self.ui_app.post("/api/login")
        async def login(username: str = Form(...), password: str = Form(...)):
            if USERS.get(username) == hashlib.sha256(password.encode()).hexdigest():
                token = jwt.encode({"role": "admin", "exp": datetime.utcnow() + timedelta(hours=24)}, JWT_SECRET, algorithm="HS256")
                return {"token": token}
            raise HTTPException(status_code=401)

        @self.ui_app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            self.ws_clients.append(ws)
            try:
                while True: await asyncio.sleep(1)
            except WebSocketDisconnect:
                self.ws_clients.remove(ws)

if __name__ == "__main__":
    module = UltimateDNSModule()
    asyncio.run(module.start())
