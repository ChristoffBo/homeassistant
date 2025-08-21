#!/usr/bin/env python3
import os, sys, json, time, re, sqlite3, datetime, threading, socketserver, collections
from http.server import BaseHTTPRequestHandler
import requests
from websocket import create_connection, WebSocketConnectionClosedException
import yaml
ENV = lambda k, d=None: os.environ.get(k, d)
GY_URL         = ENV("GY_URL")
GY_TOKEN       = ENV("GY_TOKEN")
GY_USER_TOKEN  = ENV("GY_USER_TOKEN", "")
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
HEALTHCHECK_ENABLED = (ENV("HEALTHCHECK_ENABLED", "true").lower() == "true")
FAIL_OPEN           = (ENV("FAIL_OPEN", "true").lower() == "true")
JSON_LOGS           = (ENV("JSON_LOGS", "true").lower() == "true")
DELETE_AFTER_REPOST = (ENV("DELETE_AFTER_REPOST", "true").lower() == "true")
POST_AS_APP_TOKEN   = (ENV("POST_AS_APP_TOKEN", "") or "").strip()
SELF_TEST_ON_START  = (ENV("SELF_TEST_ON_START", "true").lower() == "true")
SELF_TEST_MESSAGE   = (ENV("SELF_TEST_MESSAGE", "Gotify Bot self-test ✅") or "Gotify Bot self-test ✅")
try:
    SELF_TEST_PRIORITY = int(ENV("SELF_TEST_PRIORITY", "6") or "6")
except Exception:
    SELF_TEST_PRIORITY = 6
SELF_TEST_TARGET    = (ENV("SELF_TEST_TARGET", "clean") or "clean")
PROXY_ENABLED            = (ENV("PROXY_ENABLED", "false").lower() == "true")
PROXY_LISTEN_PORT        = int(ENV("PROXY_LISTEN_PORT", "8091") or "8091")
PROXY_FORWARD_BASE_URL   = (ENV("PROXY_FORWARD_BASE_URL", "") or "").strip()
PROXY_LOG_BODIES         = (ENV("PROXY_LOG_BODIES", "false").lower() == "true")
DATA_DB = "/data/bot.sqlite3"
RULES_PATH = "/app/rules.yaml"
LEVELS = {"DEBUG":10,"INFO":20,"WARNING":30,"ERROR":40}
def log(level, msg):
    if LEVELS[level] >= LEVELS.get(LOG_LEVEL, 20):
        print(f"[{level}] {msg}", flush=True)
def log_json(event, level="INFO", **fields):
    if not JSON_LOGS:
        return
    rec = {"ts": int(time.time()), "level": level, "event": event, **fields}
    print(json.dumps(rec, ensure_ascii=False), flush=True)
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
RECENT_POSTED = collections.deque(maxlen=200)
def mark_posted(title, message):
    RECENT_POSTED.append((f"{title}|{message}", int(time.time())))
def is_recently_posted(title, message, window=180):
    h = f"{title}|{message}"; now = int(time.time())
    return any(k == h and now - ts <= window for (k, ts) in RECENT_POSTED)
def gotify_post(title, message, priority, token_override=None) -> bool:
    tok = token_override or GY_TOKEN
    url = f"{GY_URL.rstrip('/')}/message?token={tok}"
    r = requests.post(url, json={"title": title, "message": message, "priority": int(priority)}, timeout=15)
    if r.status_code >= 300:
        log("ERROR", f"Gotify POST failed {r.status_code}: {r.text}")
        log_json("gotify_post_error", level="ERROR", status=r.status_code, body=r.text)
        return False
    mark_posted(title, message)
    log_json("gotify_post_ok", status=r.status_code, title=title, priority=priority,
             token=("override" if token_override else "default"))
    return True
def user_headers():
    if not GY_USER_TOKEN:
        return None
    return {"X-Gotify-Key": GY_USER_TOKEN, "Content-Type": "application/json"}
def gotify_list_messages(limit=100, since=0):
    h = user_headers()
    if not h: return []
    url = f"{GY_URL.rstrip('/')}/message?limit={int(limit)}&since={int(since)}"
    try:
        r = requests.get(url, headers=h, timeout=15)
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
    h = user_headers()
    if not h: return False
    url = f"{GY_URL.rstrip('/')}/message/{msg_id}"
    try:
        r = requests.delete(url, headers=h, timeout=15)
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
def to_ws_url(http_url: str) -> str:
    u = http_url.strip()
    if u.startswith("https://"):
        return "wss://" + u[len("https://"):]
    if u.startswith("http://"):
        return "ws://" + u[len("http://"):]
    if u.startswith("ws://") or u.startswith("wss://"):
        return u
    return "ws://" + u
def join_url(base, path_qs):
    base = base.rstrip("/")
    if not path_qs.startswith("/"):
        path_qs = "/" + path_qs
    return base + path_qs
def apply_yaml_rules(title, message, priority, ctx):
    for rule in YAML_RULES:
        if text_matches(rule.get("if", {}), title, message):
            actions = rule.get("then", {})
            if actions.get("suppress"):
                return True
            new_priority = int(actions.get("escalate_to", priority))
            final_title  = (actions.get("tag","") + " " + title).strip() if actions.get("tag") else title
            ok = gotify_post(final_title, message, new_priority, token_override=(POST_AS_APP_TOKEN or None))
            if ok and DELETE_AFTER_REPOST and GY_USER_TOKEN and ctx.get("msg_id"):
                gotify_delete_message(ctx["msg_id"])
            return True
    return False
def handle_message(obj):
    msg = obj.get("message", {})
    if not msg: return
    orig_title = str(msg.get("title") or "").strip()
    message    = str(msg.get("message") or "").strip()
    orig_prio  = int(msg.get("priority") or 5)
    msg_id     = msg.get("id")
    if is_recently_posted(orig_title, message): return
    if QUIET_HOURS:
        try:
            start, end = [int(x) for x in QUIET_HOURS.split("-")]
            hour = datetime.datetime.now().hour
            in_quiet = (start <= end and start <= hour < end) or (start > end and (hour >= start or hour < end))
            if in_quiet and orig_prio < QUIET_MIN_PRIORITY: return
        except Exception: pass
    new_prio = orig_prio
    for pat in PRIORITY_RAISE_REGEX:
        try:
            if re.search(pat, f"{orig_title}\n{message}"): new_prio = max(new_prio, 9)
        except re.error: pass
    for pat in PRIORITY_LOWER_REGEX:
        try:
            if re.search(pat, f"{orig_title}\n{message}"): new_prio = min(new_prio, 3)
        except re.error: pass
    new_title = orig_title
    for tr in TAG_RULES:
        m = tr.get("match"); tag = tr.get("tag")
        if m and tag and (m in new_title or m in message):
            new_title = f"{tag} {new_title}"
    ctx = {"msg_id": msg_id}
    if apply_yaml_rules(new_title, message, new_prio, ctx): return
    changed = (new_title != orig_title) or (new_prio != orig_prio)
    if changed:
        ok = gotify_post(new_title, message, new_prio, token_override=(POST_AS_APP_TOKEN or None))
        if ok and DELETE_AFTER_REPOST and GY_USER_TOKEN and msg_id:
            gotify_delete_message(msg_id)
        return
class HelpHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): return
    def do_GET(self):
        if self.path.startswith("/health"):
            self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers(); self.wfile.write(b"ok"); return
        if self.path.startswith("/help"):
            body = b"Gotify Bot running"
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_response(404); self.end_headers()
def http_server():
    try:
        with socketserver.TCPServer(("0.0.0.0", 8080), HelpHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        pass
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
        upstream_url = join_url(PROXY_FORWARD_BASE_URL, self.path)
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
        pass
def ws_loop():
    base = GY_URL.rstrip("/")
    ws_url = to_ws_url(f"{base}/stream?token={GY_TOKEN}")
    backoff = 1
    while True:
        try:
            ws = create_connection(ws_url, timeout=30)
            while True:
                raw = ws.recv()
                if not raw: raise WebSocketConnectionClosedException("empty frame")
                try:
                    obj = json.loads(raw)
                    if obj.get("event") == "message":
                        handle_message(obj)
                except Exception as e:
                    pass
        except Exception as e:
            time.sleep(backoff); backoff = min(backoff * 2, 30)
def self_test():
    if not (ENV("SELF_TEST_ON_START","true").lower()=="true"):
        return
    try:
        token = POST_AS_APP_TOKEN if ((ENV("SELF_TEST_TARGET","clean").lower()=="clean") and POST_AS_APP_TOKEN) else None
        gotify_post("Gotify Bot — Self-Test", ENV("SELF_TEST_MESSAGE","Gotify Bot self-test ✅"), int(ENV("SELF_TEST_PRIORITY","6")), token_override=token)
    except Exception as e:
        pass
def main():
    if not GY_URL or not GY_TOKEN:
        print("[gotify-bot] ERROR: gotify_url and gotify_app_token are required.", file=sys.stderr)
        sys.exit(1)
    threading.Thread(target=http_server, daemon=True).start()
    if PROXY_ENABLED:
        threading.Thread(target=http_proxy_server, daemon=True).start()
    self_test()
    ws_loop()
if __name__ == "__main__":
    main()