#!/usr/bin/env python3
import os, json, time, threading
from datetime import datetime, timezone
from urllib.parse import urljoin
from flask import Flask, send_from_directory, jsonify, request, abort
import requests

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(APP_DIR, "www")
OPTIONS_FILE = "/data/options.json"
DEFAULT_OPTIONS = {
    "listen_port": 8067,
    "gotify_url": "",
    "gotify_token": "",
    "cache_builder_list": ["google.com","microsoft.com","apple.com","youtube.com","netflix.com"],
    "servers": []
}

app = Flask(__name__, static_folder=None)

# ---------- options cache
_options_lock = threading.Lock()
_options_cache = None
_options_mtime = 0

def load_options() -> dict:
    global _options_cache, _options_mtime
    with _options_lock:
        try:
            st = os.stat(OPTIONS_FILE)
            if _options_cache is not None and st.st_mtime == _options_mtime:
                return _options_cache
            with open(OPTIONS_FILE, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = DEFAULT_OPTIONS.copy()
            os.makedirs(os.path.dirname(OPTIONS_FILE), exist_ok=True)
            with open(OPTIONS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            data = DEFAULT_OPTIONS.copy()
        _options_cache = data
        try:
            _options_mtime = os.stat(OPTIONS_FILE).st_mtime
        except Exception:
            _options_mtime = time.time()
        return data

def save_options(new_data: dict):
    global _options_cache, _options_mtime
    with _options_lock:
        current = load_options()
        current.update({k:v for k,v in new_data.items() if k != "servers"})
        if "servers" in new_data and isinstance(new_data["servers"], list):
            current["servers"] = new_data["servers"]
        with open(OPTIONS_FILE, "w") as f:
            json.dump(current, f, indent=2)
        _options_cache = current
        try:
            _options_mtime = os.stat(OPTIONS_FILE).st_mtime
        except Exception:
            _options_mtime = time.time()

def json_bool(val, default=False):
    if isinstance(val, bool): return val
    if isinstance(val, str): return val.lower() in ("1","true","yes","on")
    return default

# ---------- API: options
@app.route("/api/options", methods=["GET"])
def api_get_options():
    return jsonify({"status":"ok","options":load_options()})

@app.route("/api/options", methods=["POST"])
def api_save_options():
    data = request.get_json(force=True, silent=True) or {}
    if "servers" in data and isinstance(data["servers"], list):
        norm = []
        for s in data["servers"]:
            if not isinstance(s, dict): continue
            norm.append({
                "name": (s.get("name") or "").strip(),
                "type": (s.get("type") or "").strip().lower(),
                "base_url": (s.get("base_url") or "").strip(),
                "dns_host": (s.get("dns_host") or "").strip(),
                "dns_port": int(s.get("dns_port", 53)) if str(s.get("dns_port","")).isdigit() else 53,
                "dns_protocol": (s.get("dns_protocol") or "udp").lower(),
                "username": s.get("username","") or "",
                "password": s.get("password","") or "",
                "token": s.get("token","") or "",
                "verify_tls": json_bool(s.get("verify_tls", True), True),
                "primary": json_bool(s.get("primary", False), False),
                "cache_builder_override": json_bool(s.get("cache_builder_override", False), False),
                "cache_builder_list": s.get("cache_builder_list", []) or []
            })
        data["servers"] = norm
    if "listen_port" in data:
        try: data["listen_port"] = int(data["listen_port"])
        except Exception: data["listen_port"] = 8067
    save_options(data)
    return jsonify({"status":"ok","options":load_options()})

# ---------- upstream helpers
def _req_json(url, method="GET", headers=None, verify=True, timeout=10, data=None):
    try:
        if method == "POST":
            r = requests.post(url, headers=headers, json=data, timeout=timeout, verify=verify)
        else:
            r = requests.get(url, headers=headers, timeout=timeout, verify=verify)
        r.raise_for_status()
        return True, r.json()
    except Exception as e:
        return False, {"error": str(e)}

def fetch_stats_for_server(s):
    t = s["type"]
    base = s["base_url"].rstrip("/") + "/"
    verify = bool(s.get("verify_tls", True))
    token = s.get("token","")
    if t == "technitium":
        if not token: return {"ok": False, "error":"technitium: token required"}
        url = f"{base}api/dashboard/stats/get?token={token}&type=LastHour&utc=true"
        ok, js = _req_json(url, verify=verify)
        if not ok: return {"ok": False, "error": js.get("error","request-failed")}
        if js.get("status") != "ok": return {"ok": False, "error": js.get("errorMessage","status != ok")}
        resp = js.get("response",{})
        stats = resp.get("stats",{})
        total = int(stats.get("totalQueries",0))
        blocked = int(stats.get("totalBlocked",0))
        allowed = int(stats.get("totalNoError",0))
        return {"ok": True, "total": total, "blocked": blocked, "allowed": allowed}
    elif t == "adguard":
        headers = {}
        if token: headers["Authorization"] = f"Bearer {token}"
        ok, js = _req_json(urljoin(base,"control/stats"), headers=headers, verify=verify)
        if not ok and token:
            ok, js = _req_json(urljoin(base,f"control/stats?token={token}"), verify=verify)
        if not ok: return {"ok": False, "error": js.get("error","request-failed")}
        total = int(js.get("num_dns_queries",0))
        blocked = int(js.get("num_blocked_filtering",0))
        allowed = max(total - blocked, 0)
        return {"ok": True, "total": total, "blocked": blocked, "allowed": allowed}
    elif t == "pihole":
        url = urljoin(base, "admin/api.php?summaryRaw")
        if token: url += f"&auth={token}"
        ok, js = _req_json(url, verify=verify)
        if not ok: return {"ok": False, "error": js.get("error","request-failed")}
        total = int(js.get("dns_queries_today",0))
        blocked = int(js.get("ads_blocked_today",0))
        allowed = max(total - blocked, 0)
        return {"ok": True, "total": total, "blocked": blocked, "allowed": allowed}
    else:
        return {"ok": False, "error":"unknown-type"}

# ---------- API: stats + self-check
@app.route("/api/stats", methods=["GET"])
def api_stats():
    opts = load_options()
    servers = opts.get("servers", [])
    unified = {"total":0,"blocked":0,"allowed":0,"servers":[]}
    for s in servers:
        res = fetch_stats_for_server(s)
        entry = {"name": s.get("name",""), "type": s.get("type",""), **res}
        unified["servers"].append(entry)
        if res.get("ok"):
            unified["total"] += res["total"]
            unified["blocked"] += res["blocked"]
            unified["allowed"] += res["allowed"]
    pct_blocked = round(100.0 * unified["blocked"] / unified["total"], 2) if unified["total"] else 0.0
    return jsonify({
        "status":"ok",
        "generated": datetime.now(timezone.utc).isoformat(),
        "unified": unified,
        "pct_blocked": pct_blocked
    })

@app.route("/api/selfcheck", methods=["GET"])
def api_selfcheck():
    opts = load_options()
    out = []
    for s in opts.get("servers", []):
        res = {"name": s.get("name",""), "type": s.get("type",""), "base_url": s.get("base_url","")}
        try:
            url = s["base_url"].rstrip("/") + "/"
            verify = bool(s.get("verify_tls", True))
            if s["type"] == "technitium":
                token = s.get("token","")
                if token: r = requests.get(f"{url}api/user/session/get?token={token}", timeout=6, verify=verify)
                else:     r = requests.get(url, timeout=6, verify=verify)
            elif s["type"] == "adguard":
                r = requests.get(urljoin(url,"control/status"), timeout=6, verify=verify)
            elif s["type"] == "pihole":
                r = requests.get(urljoin(url,"admin/api.php?version"), timeout=6, verify=verify)
            else:
                r = requests.get(url, timeout=6, verify=verify)
            res["api_ok"] = (r.status_code == 200)
        except Exception as e:
            res["api_ok"] = False
            res["error"] = str(e)
        out.append(res)
    return jsonify({"status":"ok","results":out})

# ---------- static files
@app.route("/")
def serve_root():
    # index for direct /
    return send_from_directory(WWW_DIR, "index.html")

@app.route("/index.html")
def serve_index():
    # handle explicit /index.html requests (Ingress & browsers often use this)
    return send_from_directory(WWW_DIR, "index.html")

@app.route("/<path:filename>")
def serve_any(filename: str):
    """
    Serve ANY file that exists under ./www (css/js/images/charts/* etc).
    Prevent directory traversal; only allow paths within WWW_DIR.
    """
    # reject API paths so they hit API routes above
    if filename.startswith("api/"):
        abort(404)
    # secure path resolution
    full = os.path.abspath(os.path.join(WWW_DIR, filename))
    if not full.startswith(os.path.abspath(WWW_DIR) + os.sep) and full != os.path.abspath(WWW_DIR):
        abort(403)
    if os.path.isfile(full):
        # serve existing file
        rel = os.path.relpath(full, WWW_DIR)
        return send_from_directory(WWW_DIR, rel)
    # not found
    abort(404)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(load_options().get("listen_port",8067)))
    args = ap.parse_args()
    app.run(host="0.0.0.0", port=args.port)