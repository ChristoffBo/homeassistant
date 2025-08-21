#!/usr/bin/env python3
import os, sys, json, time, re, datetime, threading, socketserver, collections
from http.server import BaseHTTPRequestHandler
import requests
from websocket import create_connection, WebSocketConnectionClosedException
import yaml
from urllib.parse import quote_plus

ENV = lambda k, d=None: os.environ.get(k, d)

# ---------- Required config ----------
GY_URL       = (ENV("GY_URL") or "").strip()
GY_USERNAME  = (ENV("GY_USERNAME") or "").strip()
GY_PASSWORD  = (ENV("GY_PASSWORD") or "").strip()
POST_AS_APP_TOKEN = (ENV("POST_AS_APP_TOKEN") or "").strip()

if not GY_URL or not GY_USERNAME or not GY_PASSWORD:
    print("[gotify-bot] ERROR: gotify_url, gotify_username and gotify_password are required.", file=sys.stderr)
    sys.exit(1)
print("[GOTIFY-BOT BASIC AUTH BUILD 1.5.3] starting…", flush=True)
print(f"[CONFIG] gotify_url={GY_URL}", flush=True)
print("[CONFIG] auth=basic (username/password provided)", flush=True)

# ---------- Optional behavior ----------
QUIET_HOURS        = (ENV("QUIET_HOURS", "") or "").strip()
QUIET_MIN_PRIORITY = int(ENV("QUIET_MIN_PRIORITY", "8") or "8")
DEDUP_WINDOW_SEC   = int(ENV("DEDUP_WINDOW_SEC", "300") or "300")
SUPPRESS_REGEX        = [x for x in (ENV("SUPPRESS_REGEX", "") or "").split(",") if x]
PRIORITY_RAISE_REGEX  = [x for x in (ENV("PRIORITY_RAISE_REGEX", "") or "").split(",") if x]
PRIORITY_LOWER_REGEX  = [x for x in (ENV("PRIORITY_LOWER_REGEX", "") or "").split(",") if x]
try:
    TAG_RULES = json.loads(ENV("TAG_RULES_JSON", "[]") or "[]")
except Exception:
    TAG_RULES = []

DELETE_AFTER_REPOST = (ENV("DELETE_AFTER_REPOST", "true").lower() == "true")

RETENTION_ENABLED           = (ENV("RETENTION_ENABLED", "false").lower() == "true")
RETENTION_INTERVAL_SEC      = int(ENV("RETENTION_INTERVAL_SEC", "900") or "900")
RETENTION_MAX_AGE_HOURS     = int(ENV("RETENTION_MAX_AGE_HOURS", "24") or "24")
RETENTION_MIN_PRIORITY_KEEP = int(ENV("RETENTION_MIN_PRIORITY_KEEP", "8") or "8")
RETENTION_KEEP_APPS         = [x for x in (ENV("RETENTION_KEEP_APPS", "") or "").split(",") if x]
RETENTION_DRY_RUN           = (ENV("RETENTION_DRY_RUN", "true").lower() == "true")

ENABLE_ARCHIVING                 = (ENV("ENABLE_ARCHIVING", "false").lower() == "true")
ARCHIVE_MAX_MB                   = int(ENV("ARCHIVE_MAX_MB", "512") or "512")
ARCHIVE_TTL_HOURS_DEFAULT        = int(ENV("ARCHIVE_TTL_HOURS_DEFAULT", "168") or "168")
ARCHIVE_TTL_HOURS_HIGH           = int(ENV("ARCHIVE_TTL_HOURS_HIGH", "4320") or "4320")
ARCHIVE_TTL_HOURS_KEEP_APPS      = int(ENV("ARCHIVE_TTL_HOURS_KEEP_APPS", "720") or "720")
ARCHIVE_KEEP_APPS                = [x for x in (ENV("ARCHIVE_KEEP_APPS", "") or "").split(",") if x]
ARCHIVE_PRUNE_INTERVAL_SEC       = int(ENV("ARCHIVE_PRUNE_INTERVAL_SEC", "900") or "900")

LOG_LEVEL           = (ENV("LOG_LEVEL", "INFO") or "INFO").upper()
JSON_LOGS           = (ENV("JSON_LOGS", "true").lower() == "true")
HEALTHCHECK_ENABLED = (ENV("HEALTHCHECK_ENABLED", "true").lower() == "true")
SELF_TEST_ON_START  = (ENV("SELF_TEST_ON_START", "true").lower() == "true")
SELF_TEST_MESSAGE   = (ENV("SELF_TEST_MESSAGE", "Gotify Bot self-test \u2705") or "Gotify Bot self-test \u2705")
SELF_TEST_PRIORITY  = int(ENV("SELF_TEST_PRIORITY", "6") or "6")
SELF_TEST_TARGET    = (ENV("SELF_TEST_TARGET", "clean") or "clean")

# Proxy (optional)
PROXY_ENABLED            = (ENV("PROXY_ENABLED", "false").lower() == "true")
PROXY_LISTEN_PORT        = int(ENV("PROXY_LISTEN_PORT", "8091") or "8091")
PROXY_FORWARD_BASE_URL   = (ENV("PROXY_FORWARD_BASE_URL", "") or "").strip()
PROXY_LOG_BODIES         = (ENV("PROXY_LOG_BODIES", "false").lower() == "true")

RULES_PATH = "/app/rules.yaml"

# ---------- Logging helpers ----------
LEVELS = {"DEBUG":10,"INFO":20,"WARNING":30,"ERROR":40}
def log(level, msg):
    if LEVELS[level] >= LEVELS.get(LOG_LEVEL, 20):
        print(f"[{level}] {msg}", flush=True)

def log_json(event, level="INFO", **fields):
    if not JSON_LOGS:
        return
    rec = {"ts": int(time.time()), "level": level, "event": event, **fields}
    print(json.dumps(rec, ensure_ascii=False), flush=True)

# ---------- YAML rules ----------
try:
    with open(RULES_PATH, "r") as f:
        YAML_RULES = yaml.safe_load(f) or []
except Exception:
    YAML_RULES = []

def text_matches_clause(c, blob):
    if "contains" in c: return c["contains"] in blob
    if "regex" in c:
        try: return re.search(c["regex"], blob) is not None
        except re.error: return False
    return False

def text_matches(rule_if, title, message):
    if not rule_if: return False
    blob = f"{title}\n{message}"
    if "any" in rule_if and isinstance(rule_if["any"], list) and rule_if["any"]:
        return any(text_matches_clause(x, blob) for x in rule_if["any"])
    if "all" in rule_if and isinstance(rule_if["all"], list) and rule_if["all"]:
        return all(text_matches_clause(x, blob) for x in rule_if["all"])
    return text_matches_clause(rule_if, blob)

# ---------- Dedup ----------
RECENT_POSTED = collections.deque(maxlen=200)
def mark_posted(title, message):
    RECENT_POSTED.append((f"{title}|{message}", int(time.time())))

def is_recently_posted(title, message, window=180):
    h = f"{title}|{message}"; now = int(time.time())
    return any(k == h and now - ts <= window for (k, ts) in RECENT_POSTED)

# ---------- Post & REST helpers ----------
def gotify_post(title, message, priority, token_override=None) -> bool:
    tok = token_override or POST_AS_APP_TOKEN
    if not tok:
        log("ERROR", "post_as_app_token not set; cannot repost")
        return False
    url = f"{GY_URL.rstrip('/')}/message?token={tok}"
    r = requests.post(url, json={"title": title, "message": message, "priority": int(priority)}, timeout=15)
    if r.status_code >= 300:
        log("ERROR", f"Gotify POST failed {r.status_code}: {r.text}")
        log_json("gotify_post_error", level="ERROR", status=r.status_code, body=r.text)
        return False
    mark_posted(title, message)
    log_json("gotify_post_ok", status=r.status_code, title=title, priority=priority, token="bot_app")
    return True

def gotify_list_messages(limit=100, since=0):
    url = f"{GY_URL.rstrip('/')}/message?limit={int(limit)}&since={int(since)}"
    try:
        r = requests.get(url, timeout=15, auth=(GY_USERNAME, GY_PASSWORD))
        if r.status_code >= 300:
            log("WARNING", f"List messages failed {r.status_code}: {r.text}")
            log_json("gotify_list_error", level="WARNING", status=r.status_code, body=r.text)
            return []
        data = r.json() if r.content else {}
        msgs = data.get("messages", [])
        log_json("gotify_list_ok", count=len(msgs))
        return msgs
    except Exception as e:
        log("WARNING", f"List messages error: {e}")
        log_json("gotify_list_exception", level="WARNING", error=str(e))
        return []

def gotify_delete_message(msg_id):
    url = f"{GY_URL.rstrip('/')}/message/{msg_id}"
    try:
        r = requests.delete(url, timeout=15, auth=(GY_USERNAME, GY_PASSWORD))
        if r.status_code >= 300:
            log("WARNING", f"Delete failed {r.status_code}: {r.text}")
            log_json("retention_delete_error", level="WARNING", id=msg_id, status=r.status_code, body=r.text)
            return False
        log_json("retention_delete_ok", id=msg_id)
        return True
    except Exception as e:
        log("WARNING", f"Delete error: {e}")
        log_json("retention_delete_exception", level="WARNING", id=msg_id, error=str(e))
        return False

# ---------- WS URL builder ----------
def to_ws_url(http_url: str) -> str:
    u = http_url.strip()
    if u.startswith("https://"): return "wss://" + u[len("https://"):]
    if u.startswith("http://"):  return "ws://"  + u[len("http://"):]
    if u.startswith("ws://") or u.startswith("wss://"): return u
    return "ws://" + u

def build_ws_url():
    base = GY_URL.rstrip("/")
    ws = f"{to_ws_url(base)}/stream?username={quote_plus(GY_USERNAME)}&password={quote_plus(GY_PASSWORD)}"
    scheme = "wss" if ws.startswith("wss://") else "ws"
    print(f"[CONFIG] ws_scheme={scheme}", flush=True)
    return ws

# ---------- Processing ----------
def apply_yaml_rules(title, message, priority, ctx):
    for rule in YAML_RULES:
        if text_matches(rule.get("if", {}), title, message):
            actions = rule.get("then", {})
            if actions.get("suppress"):
                log_json("suppress_yaml", title=title)
                return True
            new_priority = int(actions.get("escalate_to", priority))
            final_title  = (actions.get("tag","") + " " + title).strip() if actions.get("tag") else title
            ok = gotify_post(final_title, message, new_priority, token_override=(POST_AS_APP_TOKEN or None))
            if ok and DELETE_AFTER_REPOST and ctx.get("msg_id"):
                gotify_delete_message(ctx["msg_id"])
            log_json("beautify_yaml_repost", title=final_title, priority=new_priority, deleted_original=bool(ok and DELETE_AFTER_REPOST and ctx.get("msg_id")))
            return True
    return False

def handle_message(obj):
    msg = obj.get("message", {})
    if not msg: return
    orig_title = str(msg.get("title") or "").strip()
    message    = str(msg.get("message") or "").strip()
    orig_prio  = int(msg.get("priority") or 5)
    msg_id     = msg.get("id")

    # Quiet hours suppression
    if QUIET_HOURS:
        try:
            start, end = [int(x) for x in QUIET_HOURS.split("-")]
            hour = datetime.datetime.now().hour
            in_quiet = (start <= end and start <= hour < end) or (start > end and (hour >= start or hour < end))
            if in_quiet and orig_prio < QUIET_MIN_PRIORITY:
                log_json("suppress_quiet_hours", title=orig_title, priority=orig_prio)
                return
        except Exception:
            pass

    # Regex-based priority adjust
    new_prio = orig_prio
    for pat in PRIORITY_RAISE_REGEX:
        try:
            if re.search(pat, f"{orig_title}\n{message}"):
                new_prio = max(new_prio, 9)
        except re.error:
            pass
    for pat in PRIORITY_LOWER_REGEX:
        try:
            if re.search(pat, f"{orig_title}\n{message}"):
                new_prio = min(new_prio, 3)
        except re.error:
            pass

    # Tag rules
    new_title = orig_title
    for tr in TAG_RULES:
        m = tr.get("match"); tag = tr.get("tag")
        if m and tag and (m in new_title or m in message):
            new_title = f"{tag} {new_title}"

    ctx = {"msg_id": msg_id}

    # YAML rules first (compound logic)
    if apply_yaml_rules(new_title, message, new_prio, ctx):
        return

    # Simple dedup protection for immediate repost loop
    if is_recently_posted(new_title, message, window=DEDUP_WINDOW_SEC):
        log_json("suppress_dedup", title=new_title)
        return

    changed = (new_title != orig_title) or (new_prio != orig_prio)
    if changed:
        ok = gotify_post(new_title, message, new_prio, token_override=(POST_AS_APP_TOKEN or None))
        if ok and DELETE_AFTER_REPOST and msg_id:
            gotify_delete_message(msg_id)
        log_json("beautify_repost", title=new_title, new_priority=new_prio, deleted_original=bool(ok and DELETE_AFTER_REPOST and msg_id))
        return

# ---------- HTTP Help/Health ----------
class HelpHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): return
    def do_GET(self):
        if self.path.startswith("/health"):
            self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers(); self.wfile.write(b"ok"); return
        if self.path.startswith("/help"):
            html = "<h1>Gotify Bot</h1><p>Running. See Supervisor logs for activity. /health returns OK.</p>"
            body = html.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_response(404); self.end_headers()

def http_server():
    try:
        with socketserver.TCPServer(("0.0.0.0", 8080), HelpHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print(f"[WARNING] help server error: {e}", flush=True)

# ---------- Minimal Proxy (optional) ----------
class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): return
    def _bad(self, code, msg):
        self.send_response(code); self.send_header("Content-Type","application/json")
        body = json.dumps({"error": msg}).encode("utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if not self.path.startswith("/message"):
            return self._bad(404, "only /message is proxied here")
        if not PROXY_FORWARD_BASE_URL:
            return self._bad(500, "proxy_forward_base_url not set")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        upstream_url = f"{PROXY_FORWARD_BASE_URL.rstrip('/')}{self.path}"
        try:
            headers = {"Content-Type": self.headers.get("Content-Type","application/json")}
            r = requests.post(upstream_url, data=body, headers=headers, timeout=20)
            content = r.content or b""
            self.send_response(r.status_code)
            for k,v in r.headers.items():
                if k.lower() in ("content-type", "content-length"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)
        except Exception as e:
            return self._bad(502, "upstream error")

def http_proxy_server():
    port = int(PROXY_LISTEN_PORT or "8091")
    try:
        with socketserver.TCPServer(("0.0.0.0", port), ProxyHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print(f"[WARNING] proxy server error: {e}", flush=True)

# ---------- WS loop ----------
def ws_loop():
    ws_url = build_ws_url()
    backoff = 1
    while True:
        try:
            print(f"[INFO] WS connect (basic-auth)", flush=True)
            ws = create_connection(ws_url, timeout=30)
            print("[INFO] WS connected", flush=True)
            backoff = 1
            while True:
                raw = ws.recv()
                if not raw: raise WebSocketConnectionClosedException("empty frame")
                try:
                    obj = json.loads(raw)
                    if obj.get("event") == "message":
                        handle_message(obj)
                except Exception as e:
                    print(f"[WARNING] WS payload error: {e}", flush=True)
        except Exception as e:
            print(f"[WARNING] WS disconnected: {e}; retry in {backoff}s", flush=True)
            time.sleep(backoff); backoff = min(backoff * 2, 30)

# ---------- Self-test ----------
def self_test():
    if not SELF_TEST_ON_START:
        return
    try:
        ok = gotify_post("Gotify Bot — Self-Test", SELF_TEST_MESSAGE, SELF_TEST_PRIORITY, token_override=(POST_AS_APP_TOKEN or None))
        print(f"[INFO] self_test_ok={ok}", flush=True)
    except Exception as e:
        print(f"[WARNING] self_test_error: {e}", flush=True)

# ---------- Main ----------
def main():
    threading.Thread(target=http_server, daemon=True).start()
    if PROXY_ENABLED:
        threading.Thread(target=http_proxy_server, daemon=True).start()
    self_test()