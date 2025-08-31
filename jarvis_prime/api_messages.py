#!/usr/bin/env python3
# api_messages.py — Inbox HTTP API + static UI for Jarvis Prime
# Serves the /ui app and exposes CRUD to the SQLite store.

import os
import json
from pathlib import Path
from aiohttp import web
import importlib.util

# ----- load local storage module by file path (avoid name clashes) -----
_THIS_DIR = Path(__file__).resolve().parent
_STORAGE_FILE = _THIS_DIR / "storage.py"
spec = importlib.util.spec_from_file_location("jarvis_storage", str(_STORAGE_FILE))
storage = importlib.util.module_from_spec(spec)  # type: ignore
assert spec and spec.loader, "Cannot load storage.py"
spec.loader.exec_module(storage)  # type: ignore

# init DB (path configurable via env JARVIS_DB_PATH)
storage.init_db(os.getenv("JARVIS_DB_PATH", "/data/jarvis.db"))

# ----- helpers -----
def _json(data, status=200):
    return web.Response(text=json.dumps(data, ensure_ascii=False), status=status, content_type="application/json")

def _ui_root() -> Path:
    # prefer /share (persisted), fallback to /app/ui (bundled)
    cand = Path("/share/jarvis_prime/ui")
    if cand.is_dir():
        return cand
    return _THIS_DIR / "ui"

# ----- API handlers -----
async def api_create_message(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return _json({"error":"bad json"}, status=400)
    title = str(data.get("title") or "Untitled")
    body = str(data.get("body") or "")
    source = str(data.get("source") or "api")
    priority = int(data.get("priority", 5))
    extras = data.get("extras") or {}
    mid = storage.save_message(title, body, source, priority, extras)  # type: ignore
    return _json({"id": int(mid)})

async def api_list_messages(request: web.Request):
    q = request.rel_url.query.get("q")
    try:
        limit = int(request.rel_url.query.get("limit", "50"))
    except Exception:
        limit = 50
    try:
        offset = int(request.rel_url.query.get("offset", "0"))
    except Exception:
        offset = 0
    items = storage.list_messages(limit=limit, q=q, offset=offset)  # type: ignore
    return _json({"items": items})

async def api_get_message(request: web.Request):
    mid = int(request.match_info["id"])
    m = storage.get_message(mid)  # type: ignore
    if not m:
        return _json({"error": "not found"}, status=404)
    return _json(m)

async def api_delete_message(request: web.Request):
    mid = int(request.match_info["id"])
    ok = storage.delete_message(mid)  # type: ignore
    return _json({"ok": bool(ok)})

async def api_mark_read(request: web.Request):
    mid = int(request.match_info["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    read = bool(body.get("read", True))
    ok = storage.mark_read(mid, read)  # type: ignore
    return _json({"ok": bool(ok)})

async def api_get_settings(request: web.Request):
    days = storage.get_retention_days()  # type: ignore
    return _json({"retention_days": int(days)})

async def api_save_settings(request: web.Request):
    data = await request.json()
    days = int(data.get("retention_days", 30))
    storage.set_retention_days(days)  # type: ignore
    return _json({"ok": True})

async def api_purge(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    days = int(data.get("days", storage.get_retention_days()))  # type: ignore
    n = storage.purge_older_than(days)  # type: ignore
    return _json({"purged": int(n)})

# ----- Static UI -----
async def index(request: web.Request):
    # Always redirect root/dir to the actual static file so it works under Ingress
    raise web.HTTPFound('/ui/index.html')

def create_app() -> web.Application:
    app = web.Application(middlewares=[
        # Ensure '/ui' redirects to '/ui/' and collapse duplicate slashes for HA Ingress
        web.normalize_path_middleware(append_slash=True, merge_slashes=True)
    ])
    # API
    app.router.add_post("/api/messages", api_create_message)
    app.router.add_get("/api/messages", api_list_messages)
    app.router.add_get("/api/messages/{id:\d+}", api_get_message)
    app.router.add_delete("/api/messages/{id:\d+}", api_delete_message)
    app.router.add_post("/api/messages/{id:\d+}/read", api_mark_read)

    app.router.add_get("/api/inbox/settings", api_get_settings)
    app.router.add_post("/api/inbox/settings", api_save_settings)
    app.router.add_post("/api/inbox/purge", api_purge)

    # UI routes
    app.router.add_get("/", index)
    app.router.add_get("/ui", index)   # no trailing slash
    app.router.add_get("/ui/", index)  # trailing slash
    # static assets
    ui_root = _ui_root()
    app.router.add_static("/ui/", path=str(ui_root), name="static", show_index=False)
    return app

def run():
    app = create_app()
    host = os.getenv("inbox_bind", "0.0.0.0")
    port = int(os.getenv("inbox_port", "2581"))
    print(f"======= Running on http://{host}:{port} =======")
    web.run_app(app, host=host, port=port)

if __name__ == "__main__":
    run()
