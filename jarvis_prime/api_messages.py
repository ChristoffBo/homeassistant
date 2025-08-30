# api_messages.py — Inbox API & UI (FULL)
from __future__ import annotations
import os, pathlib
from aiohttp import web
import storage

THIS_DIR = pathlib.Path(__file__).parent

def _ui_root() -> pathlib.Path:
    # Serve static UI from /app (index.html, style.css, app.js, icon.png)
    env = os.environ.get("UI_ROOT")
    if env and pathlib.Path(env).exists():
        return pathlib.Path(env)
    return THIS_DIR

async def index(request: web.Request) -> web.Response:
    index_path = _ui_root() / "index.html"
    if index_path.exists():
        return web.FileResponse(path=index_path)
    return web.Response(text="<h1>Jarvis Prime — Inbox</h1><p>Missing index.html</p>", content_type="text/html")

# ---- JSON API ----
async def api_list_messages(request: web.Request) -> web.Response:
    limit = int(request.query.get("limit", "200"))
    offset = int(request.query.get("offset", "0"))
    q = request.query.get("q") or None
    items = storage.list_messages(limit=limit, offset=offset, q=q)
    return web.json_response({"ok": True, "items": items})

async def api_post_message(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = (data.get("title") or "Untitled")[:200]
    body = data.get("body") or data.get("message") or ""
    source = data.get("source") or "api"
    priority = int(data.get("priority") or 5)
    extras = data.get("extras") or {}
    mid = storage.save_message(title=title, body=body, source=source, priority=priority, extras=extras, inbound=1)
    return web.json_response({"ok": True, "id": mid})

async def api_get_message(request: web.Request) -> web.Response:
    mid = int(request.match_info["id"])
    return web.json_response({"ok": True, "item": storage.get_message(mid)})

async def api_delete_message(request: web.Request) -> web.Response:
    mid = int(request.match_info["id"])
    n = storage.delete_message(mid)
    return web.json_response({"ok": True, "deleted": n})

async def api_get_settings(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "retention_days": storage.get_retention_days()})

async def api_save_settings(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    days = int(data.get("retention_days") or data.get("days") or 30)
    storage.set_retention_days(days)
    return web.json_response({"ok": True, "retention_days": storage.get_retention_days()})

async def api_purge(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    days = data.get("days")
    n = storage.purge_older_than(int(days) if days else None)
    return web.json_response({"ok": True, "purged": n})

def create_app() -> web.Application:
    storage.init_db(os.environ.get("INBOX_DB_PATH"))
    app = web.Application()
    # API
    app.router.add_get("/api/messages", api_list_messages)
    app.router.add_post("/api/messages", api_post_message)
    app.router.add_get(r"/api/messages/{id:\d+}", api_get_message)
    app.router.add_delete(r"/api/messages/{id:\d+}", api_delete_message)
    app.router.add_get("/api/inbox/settings", api_get_settings)
    app.router.add_post("/api/inbox/settings", api_save_settings)
    app.router.add_put("/api/inbox/settings", api_save_settings)         # UI compatibility
    app.router.add_post("/api/inbox/purge", api_purge)
    app.router.add_post("/api/messages/purge", api_purge)                # UI compatibility
    # UI
    app.router.add_get("/", index)
    app.router.add_get("/ui", index)
    app.router.add_get("/ui/", index)
    app.router.add_static("/ui/", path=str(_ui_root()), name="static", show_index=False)
    return app

def run():
    app = create_app()
    host = os.getenv("inbox_bind", "0.0.0.0")
    port = int(os.getenv("inbox_port", "2581"))
    print(f"[inbox] listening on {host}:{port}")
    web.run_app(app, host=host, port=port)

if __name__ == "__main__":
    run()
