import os, json, requests, socket, time, hashlib
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_from_directory
import dns.resolver

CONFIG_PATH = "/data/options.json"
STATE_DIR = "/data/unified_dns_state"
LOG_PATH = os.path.join(STATE_DIR, "logs.json")
DEDUPE_PATH = os.path.join(STATE_DIR, "gotify_dedupe.json")
os.makedirs(STATE_DIR, exist_ok=True)

# in-memory state
_stats_cache = {}   # name -> {"at": ts, "data": {...}}
_fail_until = {}    # name -> ts  (simple circuit breaker)

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"listen_port": 8067, "gotify_url": "", "gotify_token": "", "servers": [], "cache_builder_list": []}

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def load_logs():
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_logs(logs):
    with open(LOG_PATH, "w") as f:
        json.dump(logs, f, indent=2)

def log_event(kind, message, extra=None):
    entry = {"ts": datetime.utcnow().isoformat()+"Z", "kind": kind, "message": message, "extra": extra or {}}
    logs = load_logs()
    logs.append(entry)
    save_logs(logs[-5000:])
    return entry

def _dedupe_should_send(payload_hash, window_seconds=300):
    now = time.time()
    try:
        with open(DEDUPE_PATH, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    last_hash = data.get("hash"); last_ts = data.get("ts", 0)
    if last_hash == payload_hash and (now - last_ts) < window_seconds:
        return False
    data = {"hash": payload_hash, "ts": now}
    with open(DEDUPE_PATH, "w") as f:
        json.dump(data, f)
    return True

def gotify_notify(title, message, priority=5):
    cfg = load_config()
    url = (cfg.get("gotify_url") or "").rstrip("/")
    token = (cfg.get("gotify_token") or "").strip()
    if not url or not token:
        return False, "disabled"
    payload = json.dumps({"title": title, "message": message, "priority": priority}, sort_keys=True)
    phash = hashlib.sha256(payload.encode()).hexdigest()
    if not _dedupe_should_send(phash, 300):
        return False, "deduped"
    try:
        r = requests.post(url + "/message", headers={"X-Gotify-Key": token}, json=json.loads(payload), timeout=10)
        return (r.ok, f"http {r.status_code}" if not r.ok else "ok")
    except Exception as e:
        return False, str(e)

# ---------- Adapters ----------
class BaseAdapter:
    def __init__(self, spec):
        self.name = spec.get("name")
        self.type = spec.get("type")
        self.base_url = (spec.get("base_url") or "").rstrip("/")
        self.username = spec.get("username") or ""
        self.password = spec.get("password") or ""
        self.token = spec.get("token") or ""
        self.primary = bool(spec.get("primary", False))
        self.verify = bool(spec.get("verify_tls", True))
        self.dns_host = spec.get("dns_host") or urlparse(self.base_url).hostname or "127.0.0.1"
        self.dns_port = int(spec.get("dns_port") or 53)
        self.dns_protocol = (spec.get("dns_protocol") or "udp").lower()

    # Capability flags
    def cap_forwarders(self): return False
    def cap_clear_stats(self): return False
    def cap_cache_prep(self): return True  # via raw DNS queries for all types

    def check_online(self):
        until = _fail_until.get(self.name, 0)
        if until and time.time() < until:
            return False, "backoff"
        try:
            self._check()
            return True, None
        except Exception as e:
            _fail_until[self.name] = time.time() + 10
            return False, str(e)

    def get_stats(self):
        now = time.time()
        ent = _stats_cache.get(self.name)
        if ent and now - ent["at"] < 2:
            return ent["data"]
        data = {"total": 0, "blocked": 0, "topQueries": [], "topBlocked": []}
        try:
            data = self._get_stats_impl()
        except Exception as e:
            data["error"] = str(e)
        _stats_cache[self.name] = {"at": now, "data": data}
        return data

    def _get_stats_impl(self):
        return {"total": 0, "blocked": 0, "topQueries": [], "topBlocked": []}

    def list_forwarders(self): return []
    def apply_diff(self, diff, dry_run=True): return {"applied": False, "ops": diff}
    def clear_stats(self): return False

    def warm_cache(self, domains, qtypes=("A","AAAA")):
        results = []
        resolver = dns.resolver.Resolver(configure=False)
        resolver.timeout = 3
        resolver.lifetime = 5
        resolver.port = self.dns_port
        resolver.nameservers = [self.dns_host]
        for dom in domains:
            item = {"domain": dom, "ok": 0, "fail": 0}
            for qt in qtypes:
                try:
                    _ = resolver.resolve(dom, qt, raise_on_no_answer=False)
                    item["ok"] += 1
                except Exception:
                    item["fail"] += 1
            results.append(item)
        return results

    def _check(self): raise NotImplementedError

class TechnitiumAdapter(BaseAdapter):
    def cap_forwarders(self): return True
    def cap_clear_stats(self): return True

    def _api(self, path, params=None, method="GET"):
        params = params or {}
        url = self.base_url + path
        if method == "GET":
            r = requests.get(url, params=params, timeout=10, verify=self.verify)
        else:
            r = requests.post(url, data=params, timeout=10, verify=self.verify)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "ok":
            return data.get("response", data)
        if data.get("status") == "invalid-token":
            raise RuntimeError("Technitium invalid token")
        raise RuntimeError(data.get("errorMessage","Technitium API error"))

    def _check(self):
        self._api("/api/dashboard/stats/get", {"token": self.token, "type": "LastHour"})

    def _get_stats_impl(self):
        data = self._api("/api/dashboard/stats/get", {"token": self.token, "type": "LastHour", "utc": "true"})
        stats = data.get("stats", {})
        tq = [{"domain": x.get("name"), "hits": x.get("hits", 0)} for x in data.get("topDomains", [])[:3]]
        tb = [{"domain": x.get("name"), "hits": x.get("hits", 0)} for x in data.get("topBlockedDomains", [])[:3]]
        return {"total": int(stats.get("totalQueries", 0)), "blocked": int(stats.get("totalBlocked", 0)), "topQueries": tq, "topBlocked": tb}

    def list_forwarders(self):
        resp = self._api("/api/zones/list", {"token": self.token})
        zones = resp.get("zones", []) if isinstance(resp, dict) else resp
        out = []
        for z in zones:
            if z.get("type") == "Forwarder":
                out.append({"domain": z.get("name"), "target": "this-server", "protocol": "Udp", "port": 53})
        return out

    def apply_diff(self, diff, dry_run=True):
        if dry_run: return {"applied": False, "ops": diff}
        applied = {"created": 0, "deleted": 0, "skipped": 0}
        for rem in diff.get("remove", []):
            try:
                self._api("/api/zones/delete", {"token": self.token, "zone": rem["domain"]}, method="POST")
                applied["deleted"] += 1
            except Exception: applied["skipped"] += 1
        for upd in diff.get("update", []):
            try:
                self._api("/api/zones/delete", {"token": self.token, "zone": upd["domain"]}, method="POST")
            except Exception: pass
            try:
                self._api("/api/zones/create", {"token": self.token, "zone": upd["domain"], "type": "Forwarder", "initializeForwarder": "true", "protocol": upd.get("protocol","Udp"), "forwarder": upd.get("target","this-server"), "dnssecValidation": "false"}, method="POST")
            except Exception: applied["skipped"] += 1
        for add in diff.get("add", []):
            try:
                self._api("/api/zones/create", {"token": self.token, "zone": add["domain"], "type": "Forwarder", "initializeForwarder": "true", "protocol": add.get("protocol","Udp"), "forwarder": add.get("target","this-server"), "dnssecValidation": "false"}, method="POST")
                applied["created"] += 1
            except Exception: applied["skipped"] += 1
        return {"applied": True, "result": applied}

    def clear_stats(self):
        try:
            self._api("/api/dashboard/stats/deleteAll", {"token": self.token}, method="POST")
            return True
        except Exception:
            return False

class AdGuardAdapter(BaseAdapter):
    def cap_forwarders(self): return True
    def cap_clear_stats(self): return True

    def _api(self, path, method="GET", json_body=None):
        url = self.base_url + path
        auth = (self.username, self.password) if (self.username or self.password) else None
        headers = {"Accept": "application/json"}
        if method == "GET":
            r = requests.get(url, auth=auth, headers=headers, timeout=10, verify=self.verify)
        else:
            r = requests.post(url, auth=auth, headers=headers, json=json_body, timeout=10, verify=self.verify)
        r.raise_for_status()
        try: return r.json()
        except Exception: return {}

    def _check(self):
        self._api("/control/status")

    def _get_stats_impl(self):
        s = self._api("/control/stats")
        t = self._api("/control/top")
        total = int(s.get("num_dns_queries", 0)); blocked = int(s.get("num_blocked_filtering", 0))
        tq = [{"domain": d.get("domain"), "hits": d.get("count", 0)} for d in (t.get("top_queried", []) if isinstance(t, dict) else [])[:3]]
        tb = [{"domain": d.get("domain"), "hits": d.get("count", 0)} for d in (t.get("top_blocked", []) if isinstance(t, dict) else [])[:3]]
        return {"total": total, "blocked": blocked, "topQueries": tq, "topBlocked": tb}

    def list_forwarders(self):
        cfg = self._api("/control/dns_config")
        upstreams = cfg.get("upstream_dns", [])
        out = []
        for u in upstreams:
            if isinstance(u, str) and u.startswith("[/") and "]" in u:
                domain = u.split("]")[0][2:].strip("/")
                target = u.split("]")[1].strip()
                out.append({"domain": domain, "target": target, "protocol": "Udp", "port": 53})
        return out

    def _set_upstreams(self, new_upstreams):
        self._api("/control/dns_config", method="POST", json_body={"upstream_dns": new_upstreams})

    def apply_diff(self, diff, dry_run=True):
        cfg = self._api("/control/dns_config")
        upstreams = cfg.get("upstream_dns", [])
        def strip_for(dom): return [u for u in upstreams if not (isinstance(u, str) and u.startswith(f"[/"+dom+"/]"))]
        for rem in diff.get("remove", []):
            upstreams = strip_for(rem["domain"])
        for upd in diff.get("update", []):
            upstreams = strip_for(upd["domain"]); upstreams.append(f"[/{upd['domain']}/]{upd['target']}")
        for add in diff.get("add", []):
            upstreams.append(f"[/{add['domain']}/]{add['target']}")
        if dry_run: return {"applied": False, "preview_upstreams": upstreams}
        self._set_upstreams(upstreams)
        return {"applied": True}

    def clear_stats(self):
        try:
            self._api("/control/stats_reset", method="POST")
            return True
        except Exception:
            return False

class PiHoleAdapter(BaseAdapter):
    def _api(self, params):
        url = self.base_url + "/admin/api.php"
        verify = self.verify if url.startswith("https") else True
        r = requests.get(url, params=params, timeout=10, verify=verify)
        r.raise_for_status()
        return r.json()

    def _check(self):
        self._api({"summaryRaw": 1})

    def _get_stats_impl(self):
        s = self._api({"summaryRaw": 1, "auth": self.token})
        t = self._api({"topItems": 1, "auth": self.token})
        tq = []; tb = []
        if "top_queries" in t:
            for dom, cnt in list(t["top_queries"].items())[:3]:
                tq.append({"domain": dom, "hits": cnt})
        if "top_ads" in t:
            for dom, cnt in list(t["top_ads"].items())[:3]:
                tb.append({"domain": dom, "hits": cnt})
        return {"total": int(s.get("dns_queries_today", 0)), "blocked": int(s.get("ads_blocked_today", 0)), "topQueries": tq, "topBlocked": tb}

    def cap_clear_stats(self): return False
    def list_forwarders(self): return []
    def apply_diff(self, diff, dry_run=True):
        return {"applied": False, "skipped": True, "reason": "pihole-no-per-domain-forwarders"}
    def clear_stats(self): return False

def build_adapter(spec):
    t = (spec.get("type") or "").lower()
    if t == "technitium": return TechnitiumAdapter(spec)
    if t == "adguard": return AdGuardAdapter(spec)
    if t == "pihole": return PiHoleAdapter(spec)
    raise ValueError("unknown server type")

def list_adapters():
    adapters = []
    cfg = load_config()
    for s in cfg.get("servers", []):
        try: adapters.append(build_adapter(s))
        except Exception as e: log_event("config-error", f"Invalid server spec: {s}", {"error": str(e)})
    return adapters

def find_primary(adapters):
    for a in adapters:
        if a.primary: return a
    return adapters[0] if adapters else None

def normalize_fwd(forwarders):
    out = []
    for f in (forwarders or []):
        dom = (f.get("domain") or "").strip().lower().rstrip(".")
        tgt = (f.get("target") or "").strip()
        proto = (f.get("protocol") or "Udp").strip()
        port = int(f.get("port") or 53)
        if dom:
            out.append({"domain": dom, "target": tgt, "protocol": proto, "port": port})
    m = {}
    for f in out: m[f["domain"]] = f
    return list(m.values())

def diff_fwd(primary, secondary):
    p = {f["domain"]: f for f in primary}
    s = {f["domain"]: f for f in secondary}
    adds, updates, removes = [], [], []
    for dom, pf in p.items():
        if dom not in s: adds.append(pf); continue
        sf = s[dom]
        if (pf.get("target"), pf.get("protocol"), pf.get("port")) != (sf.get("target"), sf.get("protocol"), sf.get("port")):
            updates.append(pf)
    for dom in s.keys():
        if dom not in p: removes.append({"domain": dom})
    return {"add": adds, "update": updates, "remove": removes}

app = Flask(__name__, static_folder="www", static_url_path="/")

@app.route("/")
def root_index():
    return send_from_directory("www", "index.html")

# --- Config ---
@app.route("/api/config", methods=["GET","POST"])
def api_config():
    if request.method == "GET": return jsonify(load_config())
    data = request.get_json(force=True, silent=True) or {}
    cfg = load_config()
    for k in ("gotify_url","gotify_token","cache_builder_list"):
        if k in data: cfg[k] = data[k]
    save_config(cfg)
    return jsonify({"status":"ok"})

# --- Servers ---
@app.route("/api/servers", methods=["GET","POST","DELETE"])
def api_servers():
    if request.method == "GET": return jsonify({"servers": load_config().get("servers", [])})
    data = request.get_json(force=True, silent=True) or {}
    cfg = load_config(); servers = cfg.get("servers", [])
    if request.method == "POST":
        names = [s.get("name") for s in servers]
        if data.get("name") in names:
            servers = [{**s, **data} if s.get("name")==data["name"] else s for s in servers]
        else:
            servers.append(data)
        if data.get("primary"):
            for s in servers: s["primary"] = (s.get("name")==data.get("name"))
        cfg["servers"] = servers; save_config(cfg)
        return jsonify({"status":"ok", "servers": servers})
    name = data.get("name")
    servers = [s for s in servers if s.get("name") != name]
    cfg["servers"] = servers; save_config(cfg)
    return jsonify({"status":"ok", "servers": servers})

@app.route("/api/primary", methods=["POST"])
def api_primary():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    cfg = load_config(); servers = cfg.get("servers", [])
    if not any(s.get("name")==name for s in servers):
        return jsonify({"ok": False, "error":"server not found"}), 404
    for s in servers: s["primary"] = (s.get("name")==name)
    cfg["servers"] = servers; save_config(cfg)
    log_event("primary-set", f"Primary set to {name}")
    gotify_notify("Unified DNS", f"Primary set to {name}", 5)
    return jsonify({"ok": True, "primary": name})

# --- Cache Builder: global/per-server list ---
@app.route("/api/cachelist", methods=["GET","POST"])
def api_cachelist():
    cfg = load_config()
    if request.method == "GET":
        name = request.args.get("name")
        if not name:
            return jsonify({"global": cfg.get("cache_builder_list", [])})
        for s in cfg.get("servers", []):
            if s.get("name")==name:
                use_local = bool(s.get("cache_builder_override"))
                local = s.get("cache_builder_list", [])
                effective = local if use_local and local else cfg.get("cache_builder_list", [])
                return jsonify({"override": use_local, "local": local, "effective": effective})
        return jsonify({"error":"server not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    entries = data.get("entries") or []
    entries = [str(x).strip() for x in entries if str(x).strip()]
    if not name:
        cfg["cache_builder_list"] = entries
        save_config(cfg)
        return jsonify({"status":"ok","scope":"global","count":len(entries)})
    servers = cfg.get("servers", [])
    for s in servers:
        if s.get("name")==name:
            if data.get("override") is not None:
                s["cache_builder_override"] = bool(data.get("override"))
            if entries is not None:
                s["cache_builder_list"] = entries
            cfg["servers"] = servers; save_config(cfg)
            return jsonify({"status":"ok","scope":"server","name":name,"count":len(entries)})
    return jsonify({"error":"server not found"}), 404

# --- Manual cache prep ---
@app.route("/api/cacheprep", methods=["POST"])
def api_cacheprep():
    payload = request.get_json(force=True, silent=True) or {}
    name = payload.get("name")
    list_mode = (payload.get("list") or "effective").lower()
    dry = bool(payload.get("dry_run", False))
    limit = payload.get("limit")
    adapters = list_adapters()
    target = next((a for a in adapters if a.name==name), None)
    if not target: return jsonify({"error":"server not found"}), 404
    cfg = load_config()
    def effective_for(server_spec):
        if server_spec.get("cache_builder_override") and server_spec.get("cache_builder_list"):
            return server_spec.get("cache_builder_list", [])
        return cfg.get("cache_builder_list", [])
    spec = next((s for s in cfg.get("servers", []) if s.get("name")==name), None)
    if not spec: return jsonify({"error":"server spec not found"}), 404
    if list_mode=="primary":
        adapters2 = list_adapters()
        primary = find_primary(adapters2)
        if not primary: return jsonify({"error":"no primary selected"}), 400
        ps = next((s for s in cfg.get("servers", []) if s.get("name")==primary.name), None)
        domains = effective_for(ps) if ps else cfg.get("cache_builder_list", [])
    elif list_mode=="local":
        domains = spec.get("cache_builder_list", [])
    else:
        domains = effective_for(spec)
    if limit: domains = domains[:int(limit)]
    if dry:
        return jsonify({"dry_run": True, "name": name, "count": len(domains), "domains": domains})
    res = target.warm_cache(domains)
    ok = sum(1 for r in res if r["ok"]>0 and r["fail"]==0)
    log_event("cache-prep", f"Pre-cached {ok}/{len(res)} domains on {name}")
    gotify_notify("Unified DNS", f"Cache prep on {name}: {ok}/{len(res)} domains warmed", 5)
    return jsonify({"dry_run": False, "name": name, "results": res})

# --- Sync ---
@app.route("/api/sync", methods=["POST"])
def api_sync():
    payload = request.get_json(force=True, silent=True) or {}
    selected = payload.get("servers")
    dry = bool(payload.get("dry_run", True))
    categories = payload.get("categories") or {"forwarders": True}
    do_cache_prep = bool(payload.get("cache_prep", False))

    adapters = list_adapters()
    if not adapters: return jsonify({"error":"No servers configured"}), 400
    primary = find_primary(adapters)
    if not primary: return jsonify({"error":"No primary server selected"}), 400

    result = {"primary": primary.name, "servers": {}, "top3": {}, "summary": {}}
    totals = 0; blocked = 0; per_server_totals = {}
    all_top_q = []; all_top_b = []

    for a in adapters:
        ok, err = a.check_online()
        if not ok:
            result["servers"][a.name] = {"status":"offline", "error": err}
            continue
        st = a.get_stats()
        result["servers"][a.name] = {"status":"online", "stats": st}
        t=int(st.get("total",0)); b=int(st.get("blocked",0))
        totals+=t; blocked+=b; per_server_totals[a.name]=t
        all_top_q += st.get("topQueries", []); all_top_b += st.get("topBlocked", [])

    def top3(items):
        agg = {}
        for it in items:
            d=it.get("domain"); c=int(it.get("hits",0))
            if not d: continue
            agg[d]=agg.get(d,0)+c
        ordered = sorted(agg.items(), key=lambda x:x[1], reverse=True)[:3]
        return [{"domain":d, "hits":c} for d,c in ordered]

    result["top3"] = {"queried": top3(all_top_q), "blocked": top3(all_top_b), "busiest": max(per_server_totals, key=per_server_totals.get) if per_server_totals else None}
    result["summary"] = {"total": totals, "blocked": blocked, "allowed": max(0, totals-blocked)}

    if categories.get("forwarders", True):
        primary_fwd = normalize_fwd(primary.list_forwarders())
        if selected is None:
            targets = [a for a in adapters if a.name != primary.name]
        else:
            targets = [a for a in adapters if a.name in set(selected) and a.name != primary.name]
        for a in targets:
            if not a.cap_forwarders():
                result["servers"].setdefault(a.name, {}).update({"diff": None, "apply": {"applied": False, "skipped": True, "reason":"unsupported-forwarders"}})
                continue
            sec_fwd = normalize_fwd(a.list_forwarders())
            d = diff_fwd(primary_fwd, sec_fwd)
            apply_res = a.apply_diff(d, dry_run=dry)
            result["servers"].setdefault(a.name, {}).update({"diff": d, "apply": apply_res})

    if do_cache_prep and not dry:
        cfg = load_config()
        def effective_for_spec(spec):
            if spec.get("cache_builder_override") and spec.get("cache_builder_list"):
                return spec.get("cache_builder_list", [])
            return cfg.get("cache_builder_list", [])
        for a in adapters:
            if a.name == primary.name: continue
            spec = next((s for s in cfg.get("servers", []) if s.get("name")==a.name), None)
            domains = effective_for_spec(spec) if spec else cfg.get("cache_builder_list", [])
            res = a.warm_cache(domains)
            result["servers"].setdefault(a.name, {}).update({"cache_prep": {"count": len(domains), "ok": sum(1 for r in res if r["ok"] and not r["fail"])}})

    tq = ", ".join([f"{x['domain']}({x['hits']})" for x in result["top3"]["queried"]]) or "n/a"
    tb = ", ".join([f"{x['domain']}({x['hits']})" for x in result["top3"]["blocked"]]) or "n/a"
    busy = result["top3"]["busiest"] or "n/a"
    note = f"Sync {'preview' if dry else 'complete'} • Primary: {primary.name} • Busiest: {busy}\nTop Queries: {tq}\nTop Blocked: {tb}"
    gotify_notify("Unified DNS", note, 5)
    log_event("sync", note, {"dry_run": dry, "result": result})

    return jsonify(result)

# --- Clear stats ---
@app.route("/api/clear_stats", methods=["POST"])
def api_clear_stats():
    payload = request.get_json(force=True, silent=True) or {}
    name = payload.get("name")
    for a in list_adapters():
        if a.name == name:
            ok = a.clear_stats()
            msg = f"Clear stats on {name}: {'ok' if ok else 'not supported or failed'}"
            log_event("clear-stats", msg, {"server": name, "ok": ok})
            if ok: gotify_notify("Unified DNS", msg, 5)
            return jsonify({"ok": ok, "message": msg})
    return jsonify({"ok": False, "message": "server not found"}), 404

# --- Logs ---
@app.route("/api/logs", methods=["GET"])
def api_logs():
    return jsonify(load_logs())

# --- Notify test ---
@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():
    ok, msg = gotify_notify("Unified DNS Test", "This is a test message from the add-on.", 5)
    return jsonify({"ok": ok, "detail": msg})

# --- Self-check ---
@app.route("/api/selfcheck", methods=["GET"])
def api_selfcheck():
    checks = []
    cfg = load_config()
    for s in cfg.get("servers", []):
        name = s.get("name")
        try:
            adapter = build_adapter(s)
        except Exception as e:
            checks.append({"server": name, "ok": False, "phase": "init", "error": str(e)})
            continue
        # API reachability & auth
        api_ok, api_err = adapter.check_online()
        # DNS reachability (UDP/53 or TCP if configured)
        dns_ok = False; dns_err = None
        try:
            sock_type = socket.SOCK_DGRAM if adapter.dns_protocol=='udp' else socket.SOCK_STREAM
            sock = socket.socket(socket.AF_INET, sock_type)
            sock.settimeout(2)
            if adapter.dns_protocol=='udp':
                sock.sendto(b"\x00", (adapter.dns_host, adapter.dns_port))
                dns_ok = True
            else:
                sock.connect((adapter.dns_host, adapter.dns_port)); dns_ok = True
            sock.close()
        except Exception as e:
            dns_ok = False; dns_err = str(e)
        checks.append({
            "server": name,
            "type": s.get("type"),
            "api_ok": api_ok, "api_error": api_err,
            "dns_ok": dns_ok, "dns_error": dns_err,
            "verify_tls": bool(s.get("verify_tls", True))
        })
    return jsonify({"ts": datetime.utcnow().isoformat()+"Z", "checks": checks})

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("UNIFIED_DNS_PORT", "8067")))
    args = parser.parse_args()
    app.run(host="0.0.0.0", port=args.port)
