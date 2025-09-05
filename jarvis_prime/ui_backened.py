#!/usr/bin/env python3
# Jarvis Prime UI Backend (options API + static server)
# - Serves static UI (index.html, app.js, style.css, icon.png)
# - Persists Inbox messages to /data/jarvis_inbox.json
# - Options live in /data/options.json; schema+version read from /app/config.json (if present)
# - SSE stream for live updates
#
# Endpoints:
#   GET  /api/messages
#   POST /api/messages   {"title","body","source","html","saved"}
#   GET  /api/messages/<id>
#   POST /api/messages/<id>/save    (toggle or {"saved":true})
#   DELETE /api/messages/<id>
#   DELETE /api/messages?keep_saved=1
#   POST /api/inbox/purge  {"days": 30}
#   GET  /api/stream       (Server-Sent Events)
#   GET  /api/options
#   POST /api/options      (partial update; coerced by schema)
#   GET  /api/schema
#   GET  /api/version
#   POST /api/notify/quiet {"tz","start","end","allow_critical"}
#
# Run: python3 ui_backened.py  (PORT env var optional; defaults 2581)

import os, json, time, uuid, threading, queue, re
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, Response, send_from_directory, redirect
from flask_cors import CORS

APP_DIR = Path(__file__).resolve().parent
UI_DIR  = APP_DIR  # index.html, app.js, style.css expected here
DATA_DIR = Path(os.environ.get("JARVIS_DATA", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

INBOX_PATH   = DATA_DIR / "jarvis_inbox.json"
OPTIONS_PATH = DATA_DIR / "options.json"
CONFIG_PATH  = Path(os.environ.get("JARVIS_CONFIG_JSON", str(APP_DIR / "config.json")))  # includes schema+version when available

app = Flask(__name__, static_folder=None)
CORS(app)

# ------------------ storage helpers ------------------
_FILE_LOCK = threading.RLock()

def _read_json(path: Path, default):
    try:
        with _FILE_LOCK, path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    with _FILE_LOCK, tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)

def _now_ts():
    return int(time.time())

# Inbox model
def _load_inbox():
    return _read_json(INBOX_PATH, {"last_id": 0, "items": []})

def _save_inbox(doc):
    _write_json(INBOX_PATH, doc)

# Options & Schema
def _load_config_file():
    return _read_json(CONFIG_PATH, {})

def _load_schema():
    cfg = _load_config_file()
    sch = cfg.get("schema") or {}
    # ensure plain dict of str->str
    if isinstance(sch, dict):
        return sch
    return {}

def _default_options_from_config():
    cfg = _load_config_file()
    return cfg.get("options") or {}

def _load_options():
    if OPTIONS_PATH.exists():
        return _read_json(OPTIONS_PATH, {})
    # first-boot fallback to defaults from config.json if present
    defaults = _default_options_from_config()
    if defaults:
        _write_json(OPTIONS_PATH, defaults)
    return defaults or {}

def _coerce_value(key, val, schema):
    t = str(schema.get(key, "str"))
    try:
        if t.startswith("int"):
            # int(1,) style => int
            if val == "" or val is None: return 0
            return int(val)
        if t == "float":
            if val == "" or val is None: return 0.0
            return float(val)
        if t == "bool":
            if isinstance(val, bool): return val
            if isinstance(val, (int,float)): return bool(val)
            s = str(val).strip().lower()
            return s in ("1","true","yes","on")
        # string fallback
        return "" if val is None else str(val)
    except Exception:
        return val

# ------------------ SSE broadcaster ------------------
class Broker:
    def __init__(self):
        self.clients = set()
        self.lock = threading.RLock()
    def register(self):
        q = queue.Queue(maxsize=100)
        with self.lock:
            self.clients.add(q)
        return q
    def unregister(self, q):
        with self.lock:
            self.clients.discard(q)
    def publish(self, event: str, data: dict):
        payload = json.dumps({"event": event, **(data or {})}, ensure_ascii=False)
        dead = []
        with self.lock:
            for q in list(self.clients):
                try:
                    q.put_nowait(payload)
                except Exception:
                    dead.append(q)
            for q in dead:
                self.clients.discard(q)

broker = Broker()

def sse_stream(q: "queue.Queue[str]"):
    try:
        while True:
            msg = q.get()
            yield f"data: {msg}\n\n"
    except GeneratorExit:
        pass

# ------------------ API routes ------------------

@app.get("/")
def root():
    return redirect("/index.html")

@app.get("/<path:path>")
def serve_ui(path):
    # Serve static UI files from UI_DIR
    fp = (UI_DIR / path).resolve()
    if not str(fp).startswith(str(UI_DIR.resolve())) or not fp.exists():
        return ("Not found", 404)
    return send_from_directory(UI_DIR, path)

@app.get("/api/version")
def api_version():
    cfg = _load_config_file()
    ver = cfg.get("version") or _load_options().get("version") or "1.x"
    return jsonify({"version": ver})

# ---- Messages ----
@app.get("/api/messages")
def api_messages():
    inbox = _load_inbox()
    return jsonify({"items": inbox.get("items", [])})

@app.post("/api/messages")
def api_messages_post():
    body = request.get_json(force=True, silent=True) or {}
    inbox = _load_inbox()
    inbox["last_id"] = int(inbox.get("last_id", 0)) + 1
    item = {
        "id": str(inbox["last_id"]),
        "created_at": int(body.get("created_at") or _now_ts()),
        "source": body.get("source") or "api",
        "title": body.get("title") or "(no title)",
        "body": body.get("body") or "",
        "html": body.get("html") or "",
        "saved": bool(body.get("saved") or False),
    }
    inbox.setdefault("items", []).insert(0, item)
    _save_inbox(inbox)
    broker.publish("created", {"id": item["id"]})
    return jsonify(item), 201

@app.get("/api/messages/<id_>")
def api_message_get(id_):
    inbox = _load_inbox()
    for m in inbox.get("items", []):
        if str(m.get("id")) == str(id_):
            return jsonify(m)
    return ("Not found", 404)

@app.post("/api/messages/<id_>/save")
def api_message_save(id_):
    body = request.get_json(silent=True) or {}
    toggle_to = body.get("saved")
    inbox = _load_inbox()
    for m in inbox.get("items", []):
        if str(m.get("id")) == str(id_):
            if toggle_to is None:
                m["saved"] = not bool(m.get("saved"))
            else:
                m["saved"] = bool(toggle_to)
            _save_inbox(inbox)
            broker.publish("saved", {"id": id_})
            return jsonify(m)
    return ("Not found", 404)

@app.delete("/api/messages/<id_>")
def api_message_delete(id_):
    inbox = _load_inbox()
    before = len(inbox.get("items", []))
    inbox["items"] = [m for m in inbox.get("items", []) if str(m.get("id")) != str(id_)]
    _save_inbox(inbox)
    if len(inbox["items"]) < before:
        broker.publish("deleted", {"id": id_})
        return ("", 204)
    return ("Not found", 404)

@app.delete("/api/messages")
def api_messages_delete_all():
    keep_saved = request.args.get("keep_saved")
    keep = str(keep_saved or "").strip() in ("1", "true", "yes", "on")
    inbox = _load_inbox()
    if keep:
        inbox["items"] = [m for m in inbox.get("items", []) if m.get("saved")]
    else:
        inbox["items"] = []
    _save_inbox(inbox)
    broker.publish("deleted_all", {"keep_saved": keep})
    return ("", 204)

@app.post("/api/inbox/purge")
def api_inbox_purge():
    body = request.get_json(silent=True) or {}
    days = int(body.get("days") or 0)
    if days <= 0:
        return jsonify({"error": "days must be > 0"}), 400
    cutoff = _now_ts() - days*86400
    inbox = _load_inbox()
    inbox["items"] = [m for m in inbox.get("items", []) if int(m.get("created_at") or 0) >= cutoff]
    _save_inbox(inbox)
    broker.publish("purged", {"days": days})
    return jsonify({"kept": len(inbox["items"])}), 200

# ---- SSE stream ----
@app.get("/api/stream")
def api_stream():
    q = broker.register()
    def gen():
        try:
            yield "data: {}\n\n"
            for chunk in sse_stream(q):
                yield chunk
        finally:
            broker.unregister(q)
    return Response(gen(), mimetype="text/event-stream", headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})

# ---- Options & Schema ----
@app.get("/api/options")
def api_options_get():
    return jsonify(_load_options())

@app.post("/api/options")
def api_options_post():
    incoming = request.get_json(force=True, silent=True) or {}
    opts = _load_options()
    schema = _load_schema()
    for k, v in incoming.items():
        opts[k] = _coerce_value(k, v, schema)
    _write_json(OPTIONS_PATH, opts)
    broker.publish("options_saved", {"keys": list(incoming.keys())})
    return jsonify({"ok": True, "updated": list(incoming.keys())})

@app.get("/api/schema")
def api_schema_get():
    return jsonify(_load_schema())

@app.post("/api/notify/quiet")
def api_notify_quiet():
    body = request.get_json(force=True, silent=True) or {}
    tz   = body.get("tz") or ""
    start= body.get("start") or ""
    end  = body.get("end") or ""
    allow= bool(body.get("allow_critical"))
    opts = _load_options()
    # Best-effort: compress into personality_quiet_hours and store extra keys too
    if start and end:
        opts["personality_quiet_hours"] = f"{start}-{end}"
    if tz:
        opts["jarvis_timezone"] = tz
    opts["quiet_allow_critical"] = allow
    _write_json(OPTIONS_PATH, opts)
    broker.publish("options_saved", {"keys": ["personality_quiet_hours","jarvis_timezone","quiet_allow_critical"]})
    return jsonify({"ok": True})

# -------------- main --------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "2581"))
    # Serve with Flask's built-in server. For production, front with HA Ingress or a reverse proxy.
    app.run(host="0.0.0.0", port=port, threaded=True)
