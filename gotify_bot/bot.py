#!/usr/bin/env python3
import os, sys, json, time, re, sqlite3, datetime, threading, socketserver, collections
from http.server import BaseHTTPRequestHandler
import requests
from websocket import create_connection, WebSocketConnectionClosedException
import yaml

ENV = lambda k, d=None: os.environ.get(k, d)

# ---------------- Config from env ----------------
GY_URL         = ENV("GY_URL")
GY_TOKEN       = ENV("GY_TOKEN")              # Application token (stream/post)
GY_USER_TOKEN  = ENV("GY_USER_TOKEN", "")

QUIET_HOURS        = (ENV("QUIET_HOURS", "") or "").strip()    # e.g. "22-06"
QUIET_MIN_PRIORITY = int(ENV("QUIET_MIN_PRIORITY", "8") or "8")
DEDUP_WINDOW_SEC   = int(ENV("DEDUP_WINDOW_SEC", "300") or "300")

SUPPRESS_REGEX        = [x for x in (ENV("SUPPRESS_REGEX", "") or "").split(",") if x]
PRIORITY_RAISE_REGEX  = [x for x in (ENV("PRIORITY_RAISE_REGEX", "") or "").split(",") if x]
PRIORITY_LOWER_REGEX  = [x for x in (ENV("PRIORITY_LOWER_REGEX", "") or "").split(",") if x]

# JSON rules for tagging (list of {"match","tag"})
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
SELF_TEST_TARGET    = (ENV("SELF_TEST_TARGET", "clean") or "clean")  # "clean" or "raw"

DATA_DB = "/data/bot.sqlite3"
RULES_PATH = "/app/rules.yaml"

# ---------------- Logging ----------------
LEVELS = {"DEBUG":10,"INFO":20,"WARNING":30,"ERROR":40}
def log(level, msg):
    if LEVELS[level] >= LEVELS.get(LOG_LEVEL, 20):
        print(f"[{level}] {msg}", flush=True)

def log_json(event, level="INFO", **fields):
    if not JSON_LOGS:
        return
    rec = {"ts": int(time.time()), "level": level, "event": event, **fields}
    print(json.dumps(rec, ensure_ascii=False), flush=True)

# ---------------- Archive + Dedup ----------------
if ENABLE_ARCHIVING:
    conn = sqlite3.connect(DATA_DB, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      priority INTEGER NOT NULL,
      title TEXT,
      message TEXT,
      app TEXT,
      token TEXT,
      hash TEXT
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hash_ts ON messages(hash, ts)")
    conn.commit()
else:
    conn = None; cur = None

def msg_hash(title, message): return f"{title}|{message}"

def archive_and_is_dup(title, message, priority, app, token, window=DEDUP_WINDOW_SEC):
    h = msg_hash(title, message)
    now = int(time.time())
    if ENABLE_ARCHIVING and cur:
        cur.execute("INSERT INTO messages(ts,priority,title,message,app,token,hash) VALUES (?,?,?,?,?,?,?)",
                    (now, priority, title, message, app or "", token or "", h))
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM messages WHERE hash=? AND ts>=?", (h, now - window))
        dup = cur.fetchone()[0] > 1
        if dup: log_json("dedup_window_hit", title=title, priority=priority, window_sec=window)
        return dup
    return False

# ---------------- Optional YAML rules (first-match wins) ----------------
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

# ---------------- Loop guard for self-reposts ----------------
RECENT_POSTED = collections.deque(maxlen=200)  # (hash, ts)
def mark_posted(title, message):
    RECENT_POSTED.append((f"{title}|{message}", int(time.time())))

def is_recently_posted(title, message, window=180):
    h = f"{title}|{message}"; now = int(time.time())
    return any(k == h and now - ts <= window for (k, ts) in RECENT_POSTED)

# ---------------- Gotify helpers ----------------
def gotify_post(title, message, priority, token_override=None):
    tok = token_override or GY_TOKEN
    url = f"{GY_URL.rstrip('/')}/message?token={tok}"
    r = requests.post(url, json={"title": title, "message": message, "priority": int(priority)}, timeout=15)
    if r.status_code >= 300:
        log("ERROR", f"Gotify POST failed {r.status_code}: {r.text}")
        log_json("gotify_post_error", level="ERROR", status=r.status_code, body=r.text)
    else:
        mark_posted(title, message)
        log_json("gotify_post_ok", status=r.status_code, title=title, priority=priority, token=("override" if token_override else "default"))

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

# ---------------- Actions & processing ----------------
def do_http_post(url, headers, body):
    if not url: return
    try:
        r = requests.post(url, json=body, headers=headers or {}, timeout=20)
        if r.status_code >= 300:
            log("WARNING", f"Webhook {url} -> {r.status_code}: {r.text}")
            log_json("webhook_post_error", level="WARNING", url=url, status=r.status_code)
        else:
            log_json("webhook_post_ok", url=url, status=r.status_code)
    except Exception as e:
        log("ERROR", f"Webhook error: {e}")
        log_json("webhook_post_exception", level="ERROR", url=url, error=str(e))

def apply_yaml_rules(title, message, priority, ctx):
    for rule in YAML_RULES:
        if text_matches(rule.get("if", {}), title, message):
            actions = rule.get("then", {})
            if actions.get("suppress"):
                sw = int(actions.get("suppress_window_sec", 0) or DEDUP_WINDOW_SEC)
                _ = archive_and_is_dup(title, message, priority, app=None, token=GY_TOKEN, window=sw)
                log("INFO", f"suppress by YAML rule '{rule.get('name','')}'")
                log_json("suppress_yaml_rule", rule=rule.get("name",""), window_sec=sw, title=title)
                return True
            new_priority = int(actions.get("escalate_to", priority))
            final_title  = (actions.get("tag","") + " " + title).strip() if actions.get("tag") else title
            # Repost if anything changed
            if new_priority != priority or actions.get("tag"):
                gotify_post(final_title, message, new_priority, token_override=(POST_AS_APP_TOKEN or None))
                log_json("escalate_repost", rule=rule.get("name",""), old_priority=priority, new_priority=new_priority, title=final_title)
                if DELETE_AFTER_REPOST and GY_USER_TOKEN and ctx.get("msg_id"):
                    gotify_delete_message(ctx["msg_id"])
            if "http_post" in actions:
                act = actions["http_post"]
                body = {k: (str(v).replace("{title}", title).replace("{message}", message).replace("{priority}", str(new_priority))
                       if isinstance(v,str) else v) for k,v in (act.get("json", {}) or {}).items()}
                do_http_post(act.get("url"), act.get("headers"), body)
            return True
    return False

def handle_message(obj):
    msg = obj.get("message", {})
    if not msg: return
    orig_title = str(msg.get("title") or "").strip()
    message    = str(msg.get("message") or "").strip()
    orig_prio  = int(msg.get("priority") or 5)
    app        = str(msg.get("app") or "") if isinstance(msg.get("app"), str) else str(msg.get("appid") or "")
    msg_id     = msg.get("id")

    # Skip our own reposts
    if is_recently_posted(orig_title, message):
        log_json("self_post_skip", title=orig_title)
        return

    # Archive/dedup (if enabled)
    if archive_and_is_dup(orig_title, message, orig_prio, app, msg.get("token")):
        log("DEBUG", "dedup: archived identical message in window; no action")
        return

    # Hard suppress via SUPPRESS_REGEX
    for pat in SUPPRESS_REGEX:
        try:
            if re.search(pat, f"{orig_title}\n{message}"):
                log("INFO", f"suppress by SUPPRESS_REGEX '{pat}'")
                log_json("suppress_regex", pattern=pat, title=orig_title)
                return
        except re.error:
            continue

    # Quiet hours suppression
    if QUIET_HOURS:
        try:
            start, end = [int(x) for x in QUIET_HOURS.split("-")]
            hour = datetime.datetime.now().hour
            in_quiet = (start <= end and start <= hour < end) or (start > end and (hour >= start or hour < end))
            if in_quiet and orig_prio < QUIET_MIN_PRIORITY:
                log("INFO", f"quiet-hours: suppressed prio {orig_prio} < {QUIET_MIN_PRIORITY}")
                log_json("suppress_quiet_hours", priority=orig_prio, min_priority=QUIET_MIN_PRIORITY, title=orig_title)
                return
        except Exception:
            pass

    # Priority adjustments
    new_prio = orig_prio
    for pat in PRIORITY_RAISE_REGEX:
        try:
            if re.search(pat, f"{orig_title}\n{message}"):
                new_prio = max(new_prio, 9)
                log_json("priority_raise", pattern=pat, new_priority=new_prio, title=orig_title)
        except re.error:
            continue
    for pat in PRIORITY_LOWER_REGEX:
        try:
            if re.search(pat, f"{orig_title}\n{message}"):
                new_prio = min(new_prio, 3)
                log_json("priority_lower", pattern=pat, new_priority=new_prio, title=orig_title)
        except re.error:
            continue

    # Tag rules (simple prefix)
    new_title = orig_title
    for tr in TAG_RULES:
        m = tr.get("match"); tag = tr.get("tag")
        if m and tag and (m in new_title or m in message):
            new_title = f"{tag} {new_title}"
            log_json("tag_applied", tag=tag, match=m, title=new_title)

    # Apply YAML actions (if any; may repost & delete)
    ctx = {"msg_id": msg_id}
    if apply_yaml_rules(new_title, message, new_prio, ctx):
        return

    # If anything changed (title or priority), repost beautified copy (to alt app if set), then optionally delete original
    changed = (new_title != orig_title) or (new_prio != orig_prio)
    if changed:
        gotify_post(new_title, message, new_prio, token_override=(POST_AS_APP_TOKEN or None))
        log_json("beautify_repost", old_title=orig_title, new_title=new_title, old_priority=orig_prio, new_priority=new_prio)
        if DELETE_AFTER_REPOST and GY_USER_TOKEN and msg_id:
            gotify_delete_message(msg_id)
        return

    # Otherwise: no change; archived-only (if archiving enabled)
    log("DEBUG", "no change; archived only")
    log_json("archive_only", title=orig_title, priority=orig_prio)

# ---------------- Retention worker (Gotify inbox clean) ----------------
def gotify_list_all_ids_for_deletion(cutoff_dt):
    since = 0; to_delete = []
    for _ in range(10):
        msgs = gotify_list_messages(limit=100, since=since)
        if not msgs: break
        for m in msgs:
            mid   = m.get("id")
            prio  = int(m.get("priority", 5))
            app   = (m.get("app") or "") if isinstance(m.get("app"), str) else (m.get("appid") or "")
            date  = m.get("date")
            try:
                m_dt = datetime.datetime.fromisoformat(date.replace("Z","+00:00")) if date else None
            except Exception:
                m_dt = None
            keep_for_app = app in RETENTION_KEEP_APPS if app else False
            keep_for_pri = prio >= RETENTION_MIN_PRIORITY_KEEP
            old_enough   = (m_dt is None) or (m_dt < cutoff_dt)
            if not keep_for_app and not keep_for_pri and old_enough:
                to_delete.append(mid)
        since = msgs[-1]["id"]
    return to_delete

def retention_worker():
    if not RETENTION_ENABLED:
        log("INFO", "retention disabled"); return
    if not GY_USER_TOKEN:
        log("WARNING", "retention enabled but GY_USER_TOKEN missing; cannot delete"); return
    log("INFO", "retention worker started")
    log_json("retention_started", enabled=True, max_age_h=RETENTION_MAX_AGE_HOURS, keep_prio=RETENTION_MIN_PRIORITY_KEEP)
    while True:
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=RETENTION_MAX_AGE_HOURS)
            to_delete = gotify_list_all_ids_for_deletion(cutoff)
            if to_delete:
                log("INFO", f"retention: deleting {len(to_delete)} messages")
                ok = 0
                if RETENTION_DRY_RUN:
                    for _mid in to_delete:
                        log_json("retention_delete_dry_run", id=_mid)
                    ok = len(to_delete)
                else:
                    for mid in to_delete:
                        if gotify_delete_message(mid): ok += 1
                log("INFO", f"retention: deleted {ok}/{len(to_delete)}")
                log_json("retention_delete", deleted=ok, selected=len(to_delete), max_age_h=RETENTION_MAX_AGE_HOURS)
            else:
                log("DEBUG", "retention: nothing to delete")
                log_json("retention_nop")
        except Exception as e:
            log("WARNING", f"retention worker error: {e}")
            log_json("retention_error", level="WARNING", error=str(e))
        time.sleep(RETENTION_INTERVAL_SEC)

# ---------------- Archive prune ----------------
def archive_prune_worker():
    if not ENABLE_ARCHIVING or not conn:
        return
    log("INFO", "archive prune worker started")
    log_json("archive_prune_started")
    while True:
        try:
            now = int(time.time())
            cur.execute("DELETE FROM messages WHERE priority < ? AND ts < ?", (8, now - ARCHIVE_TTL_HOURS_DEFAULT*3600))
            cur.execute("DELETE FROM messages WHERE priority >= ? AND ts < ?", (8, now - ARCHIVE_TTL_HOURS_HIGH*3600))
            if ARCHIVE_KEEP_APPS:
                placeholders = ",".join("?"*len(ARCHIVE_KEEP_APPS))
                cur.execute(f"DELETE FROM messages WHERE app NOT IN ({placeholders}) AND ts < ?", (*ARCHIVE_KEEP_APPS, now - ARCHIVE_TTL_HOURS_DEFAULT*3600))
            conn.commit()
            cur.execute("PRAGMA page_size"); page_size = cur.fetchone()[0]
            cur.execute("PRAGMA page_count"); page_count = cur.fetchone()[0]
            mb = (page_size*page_count)/(1024*1024)
            if mb > ARCHIVE_MAX_MB:
                cur.execute("DELETE FROM messages WHERE id IN (SELECT id FROM messages ORDER BY ts ASC LIMIT 1000)")
                conn.commit()
            cur.execute("VACUUM"); conn.commit()
            log_json("archive_prune_ok", db_mb=mb)
        except Exception as e:
            log("WARNING", f"archive prune error: {e}")
            log_json("archive_prune_error", level="WARNING", error=str(e))
        time.sleep(ARCHIVE_PRUNE_INTERVAL_SEC)

# ---------------- Tiny HTTP server: /health, /help ----------------
HELP_HTML = None
def build_help_html():
    global HELP_HTML
    opts = {
        "Gotify URL": (GY_URL, "Where to send/read notifications."),
        "App Token": ("***" if GY_TOKEN else "(not set)", "Application token (Required) used to read stream and post messages."),
        "User Token": ("***" if GY_USER_TOKEN else "(not set)", "User token (Optional) required for deletes and retention."),
        "Quiet Hours": (QUIET_HOURS or "(disabled)", "Suppress low-priority alerts during HH-HH."),
        "Quiet Min Priority": (QUIET_MIN_PRIORITY, "Below this, messages are suppressed during quiet hours."),
        "Dedup Window (sec)": (DEDUP_WINDOW_SEC, "Identical messages within this window are collapsed."),
        "Suppress Regex": (SUPPRESS_REGEX or "(none)", "Patterns to drop entirely."),
        "Raise Priority Regex": (PRIORITY_RAISE_REGEX or "(none)", "Patterns that are bumped to high priority."),
        "Lower Priority Regex": (PRIORITY_LOWER_REGEX or "(none)", "Patterns lowered to low priority."),
        "Tag Rules": (TAG_RULES or "(none)", "If match is found in title/message, tag is prefixed to the title."),
        "Retention Enabled": (RETENTION_ENABLED, "Auto-clean Gotify inbox by age/priority/app (requires user token)."),
        "Retention Max Age (h)": (RETENTION_MAX_AGE_HOURS, "Delete older than this (unless kept)."),
        "Retention Keep Priority ≥": (RETENTION_MIN_PRIORITY_KEEP, "Do not delete messages at or above this priority."),
        "Retention Keep Apps": (RETENTION_KEEP_APPS or "(none)", "Do not delete messages from these apps."),
        "Retention Dry Run": (RETENTION_DRY_RUN, "Log only; do not delete."),
        "Archiving Enabled": (ENABLE_ARCHIVING, "If enabled, all messages are stored to /data/bot.sqlite3."),
        "Archive Max MB": (ARCHIVE_MAX_MB, "Soft cap; oldest are purged when exceeded."),
        "Archive TTL Default (h)": (ARCHIVE_TTL_HOURS_DEFAULT, "Normal messages retention."),
        "Archive TTL High (h)": (ARCHIVE_TTL_HOURS_HIGH, "High-priority messages retention."),
        "Archive TTL Keep Apps (h)": (ARCHIVE_TTL_HOURS_KEEP_APPS, "TTL for messages from archive_keep_apps."),
        "Archive Keep Apps": (ARCHIVE_KEEP_APPS or "(none)", "Apps to retain longer in archive."),
        "Log Level": (LOG_LEVEL, "DEBUG, INFO, WARNING, ERROR."),
        "Fail Open": (FAIL_OPEN, "If bot crashes, Gotify still works normally."),
        "JSON Logs": (JSON_LOGS, "Emit structured JSON lines in addition to human-readable logs."),
        "Delete Original After Repost": (DELETE_AFTER_REPOST, "If enabled, delete raw after posting beautified copy."),
        "Post As App Token": (POST_AS_APP_TOKEN or "(none)", "If set, beautified messages go to this Application token (Clean Feed)."),
        "Self-Test On Start": (SELF_TEST_ON_START, "If enabled, send a test message at startup."),
        "Self-Test Message": (SELF_TEST_MESSAGE, "Text of the test message."),
        "Self-Test Priority": (SELF_TEST_PRIORITY, "Priority for the test message."),
        "Self-Test Target": (SELF_TEST_TARGET, "Send test to 'raw' (default token) or 'clean' (post_as_app_token).")
    }
    rows = "\n".join(
        f"<tr><td><b>{k}</b></td><td>{opts[k][0]}</td><td>{opts[k][1]}</td></tr>"
        for k in opts
    )
    HELP_HTML = f"""<!doctype html><html><head>
    <meta charset="utf-8"><title>Gotify Bot Help</title>
    <style>
    body{{font-family:system-ui,Arial,sans-serif;margin:20px;}}
    table{{border-collapse:collapse;width:100%;}}
    td,th{{border:1px solid #ddd;padding:8px;vertical-align:top;}}
    th{{background:#f6f6f6;text-align:left;}}
    code{{background:#f2f2f2;padding:2px 4px;border-radius:4px;}}
    </style></head><body>
    <h1>Gotify Bot — Help & Current Configuration</h1>
    <p>Configure options in the Home Assistant add-on <b>Configuration</b> tab, then restart the add-on.</p>
    <table><tr><th>Option</th><th>Current Value</th><th>What it does</th></tr>
    {rows}
    </table>
    <p>Endpoints: <code>/health</code> (ok), <code>/help</code> (this page).</p>
    </body></html>"""

class HelpHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        return
    def do_GET(self):
        global HELP_HTML
        if self.path.startswith("/health"):
            self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers()
            self.wfile.write(b"ok"); return
        if self.path.startswith("/help"):
            if HELP_HTML is None: build_help_html()
            body = HELP_HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body); return
        self.send_response(404); self.end_headers()

def http_server():
    try:
        with socketserver.TCPServer(("0.0.0.0", 8080), HelpHandler) as httpd:
            log("INFO", "help server on :8080 (/help, /health)")
            log_json("help_server_started", port=8080)
            httpd.serve_forever()
    except Exception as e:
        log("WARNING", f"http server error: {e}")
        log_json("help_server_error", level="WARNING", error=str(e))

# ---------------- WS loop ----------------
def ws_loop():
    ws_url = f"{GY_URL.rstrip('/')}/stream?token={GY_TOKEN}"
    backoff = 1
    while True:
        try:
            log("INFO", f"WS connect {ws_url}")
            log_json("ws_connect", url=ws_url)
            ws = create_connection(ws_url, timeout=30)
            log("INFO", "WS connected")
            log_json("ws_connected")
            backoff = 1
            while True:
                raw = ws.recv()
                if not raw: raise WebSocketConnectionClosedException("empty frame")
                try:
                    obj = json.loads(raw)
                    if obj.get("event") == "message":
                        handle_message(obj)
                except Exception as e:
                    log("WARNING", f"bad frame: {e}")
                    log_json("ws_bad_frame", level="WARNING", error=str(e))
        except Exception as e:
            log("WARNING", f"WS disconnected: {e}; retry in {backoff}s")
            log_json("ws_disconnected", level="WARNING", error=str(e), backoff=backoff)
            time.sleep(backoff); backoff = min(backoff * 2, 30)

# ---------------- Startup helpers ----------------
def self_test():
    if not SELF_TEST_ON_START:
        return
    try:
        token = None
        if SELF_TEST_TARGET.lower() == "clean" and POST_AS_APP_TOKEN:
            token = POST_AS_APP_TOKEN
        gotify_post("Gotify Bot — Self-Test", SELF_TEST_MESSAGE, SELF_TEST_PRIORITY, token_override=token)
        log_json("self_test_ok", target=("clean" if token else "raw"), priority=SELF_TEST_PRIORITY)
    except Exception as e:
        log_json("self_test_error", level="ERROR", error=str(e))

# ---------------- Main ----------------
def main():
    if not GY_URL or not GY_TOKEN:
        print("[gotify-bot] ERROR: gotify_url and gotify_app_token are required.", file=sys.stderr)
        sys.exit(1)

    if RETENTION_ENABLED:
        threading.Thread(target=retention_worker, daemon=True).start()
    if ENABLE_ARCHIVING:
        threading.Thread(target=archive_prune_worker, daemon=True).start()
    if HEALTHCHECK_ENABLED:
        threading.Thread(target=http_server, daemon=True).start()

    self_test()
    ws_loop()

if __name__ == "__main__":
    main()