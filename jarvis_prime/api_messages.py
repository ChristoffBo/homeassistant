#!/usr/bin/env python3
# api_messages.py — REST API for Jarvis Prime Unified Inbox + simple push endpoint
import os
import json
from wsgiref.simple_server import make_server
from urllib.parse import parse_qs
from io import BytesIO
import traceback
import requests

# Local modules
import storage

# ----- Config -----
HOST = os.getenv("API_BIND", "0.0.0.0")
PORT = int(os.getenv("API_PORT", "8080"))
PROXY_BIND = os.getenv("proxy_bind", "127.0.0.1")
PROXY_PORT = int(os.getenv("proxy_port", "2580"))

def _resp(start_response, code=200, body=b"ok", ctype="application/json", extra_headers=None):
    headers = [
        ("Content-Type", ctype),
        ("Cache-Control", "no-store"),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    start_response(f"{code} OK" if code == 200 else f"{code} ERROR", headers)
    return [body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")]

def _json(start_response, obj, code=200):
    return _resp(start_response, code=code, body=json.dumps(obj, ensure_ascii=False).encode("utf-8"))

def _bad(start_response, msg="bad request", code=400):
    return _json(start_response, {"error": msg}, code=code)

def _read_json(env):
    try:
        length = int(env.get("CONTENT_LENGTH", "0"))
        raw = env["wsgi.input"].read(length) if length > 0 else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}

def _route_messages(env, start_response, path):
    # GET /api/messages?limit=50&q=...&offset=0
    if env["REQUEST_METHOD"] == "GET":
        qs = parse_qs(env.get("QUERY_STRING",""))
        limit = int(qs.get("limit", ["50"])[0])
        q = qs.get("q", [""])[0] or None
        offset = int(qs.get("offset", ["0"])[0])
        try:
            data = storage.list_messages(limit=limit, q=q, offset=offset)
            return _json(start_response, {"items": data, "count": len(data)})
        except Exception as e:
            print("[api] list_messages error:", e)
            traceback.print_exc()
            return _bad(start_response, "list error", code=500)
    # DELETE /api/messages/<id>
    if env["REQUEST_METHOD"] == "DELETE":
        try:
            mid = int(path.split("/")[-1])
            ok = storage.delete_message(mid)
            return _json(start_response, {"deleted": bool(ok)})
        except Exception:
            return _bad(start_response, "delete error", code=500)
    # OPTIONS
    if env["REQUEST_METHOD"] == "OPTIONS":
        return _resp(start_response, 200, b"", "text/plain")
    return _bad(start_response, "method not allowed", code=405)

def _route_message(env, start_response, mid):
    if env["REQUEST_METHOD"] == "GET":
        m = storage.get_message(int(mid))
        return _json(start_response, {"item": m} if m else {"item": None})
    if env["REQUEST_METHOD"] == "OPTIONS":
        return _resp(start_response, 200, b"", "text/plain")
    return _bad(start_response, "method not allowed", code=405)

def _route_settings(env, start_response):
    if env["REQUEST_METHOD"] == "GET":
        days = storage.get_retention_days()
        return _json(start_response, {"retention_days": days})
    if env["REQUEST_METHOD"] == "POST":
        data = _read_json(env)
        days = int(data.get("retention_days", 30))
        storage.set_retention_days(days)
        return _json(start_response, {"retention_days": storage.get_retention_days()})
    if env["REQUEST_METHOD"] == "OPTIONS":
        return _resp(start_response, 200, b"", "text/plain")
    return _bad(start_response, "method not allowed", code=405)

def _route_purge(env, start_response):
    if env["REQUEST_METHOD"] == "POST":
        data = _read_json(env)
        days = int(data.get("days", 30))
        n = storage.purge_older_than(days)
        return _json(start_response, {"purged": n})
    if env["REQUEST_METHOD"] == "OPTIONS":
        return _resp(start_response, 200, b"", "text/plain")
    return _bad(start_response, "method not allowed", code=405)

def _route_push(env, start_response):
    """POST /api/push  -> forwards to local proxy so normal pipeline runs (LLM/beautify + DB save)."""
    if env["REQUEST_METHOD"] == "POST":
        data = _read_json(env)
        title = (data.get("title") or "Message").strip()
        message = str(data.get("message") or "").strip()
        priority = int(data.get("priority") or 5)
        if not message:
            return _bad(start_response, "message required")
        try:
            url = f"http://{PROXY_BIND}:{PROXY_PORT}/"
            payload = {"title": title, "message": message, "priority": priority}
            r = requests.post(url, json=payload, headers={"Content-Type":"application/json", "X-Title": title}, timeout=8)
            r.raise_for_status()
            return _json(start_response, {"ok": True})
        except Exception as e:
            print("[api] push error:", e)
            return _bad(start_response, f"push failed: {e}", code=500)
    if env["REQUEST_METHOD"] == "OPTIONS":
        return _resp(start_response, 200, b"", "text/plain")
    return _bad(start_response, "method not allowed", code=405)

def app(env, start_response):
    try:
        path = env.get("PATH_INFO","")
        if path == "/":
            return _resp(start_response, 200, b"ok", "text/plain")
        if path.startswith("/api/messages/") and env["REQUEST_METHOD"] in ("GET","DELETE","OPTIONS"):
            return _route_messages(env, start_response, path)
        if path == "/api/messages" and env["REQUEST_METHOD"] in ("GET","OPTIONS"):
            return _route_messages(env, start_response, path)
        if path.startswith("/api/message/"):
            mid = path.split("/")[-1]
            return _route_message(env, start_response, mid)
        if path == "/api/inbox/settings":
            return _route_settings(env, start_response)
        if path == "/api/inbox/purge":
            return _route_purge(env, start_response)
        if path == "/api/push":
            return _route_push(env, start_response)
        return _bad(start_response, "not found", code=404)
    except Exception as e:
        print("[api] fatal:", e)
        traceback.print_exc()
        return _bad(start_response, "internal error", code=500)

if __name__ == "__main__":
    storage.init_db()
    httpd = make_server(HOST, PORT, app)
    print(f"[api] listening on {HOST}:{PORT} (proxy forward {PROXY_BIND}:{PROXY_PORT})")
    httpd.serve_forever()
