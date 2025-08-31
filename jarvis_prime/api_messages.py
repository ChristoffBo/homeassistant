#!/usr/bin/env python3
# api_messages.py — Inbox HTTP API + static UI for Jarvis Prime
# Serves UI from /app/www (bundled in the add-on). Also exposes JSON API + optional /api/wake passthrough.

import os, json, asyncio
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

# ----- SSE broadcaster -----
_listeners = set()

async def _sse(request: web.Request):
    resp = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
        }
    )
    await resp.prepare(request)
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _listeners.add(q)
    # initial ping
    await resp.write(b": hello\\n\\n")
    try:
        while True:
            data = await q.get()
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            try:
                await resp.write(b"data: " + payload + b"\\n\\n")
            except (ConnectionResetError, RuntimeError, BrokenPipeError):
                break
    except asyncio.CancelledError:
        pass
    finally:
        _listeners.discard(q)
        try:
            await resp.write_eof()
        except Exception:
            pass
    return resp

def _broadcast(event: str, **kw):
    dead = []
    for q in list(_listeners):
        try:
            q.put_nowait({"event": event, **kw})
        except Exception:
            dead.append(q)
    for q in dead:
        _listeners.discard(q)

# ----- helpers -----
def _json(data, status=200):
    return web.Response(text=json.dumps(data, ensure_ascii=False), status=status, content_type="application/json")

def _ui_root() -> Path:
    # Home Assistant add-on convention: serve bundled UI from /app/www
    return Path("/app/www")

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
    _broadcast("created", id=int(mid))
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
    saved = request.rel_url.query.get("saved")
    saved_bool = None
    if saved is not None:
        try:
            saved_bool = bool(int(saved))
        except Exception:
            saved_bool = saved.lower() in ('1','true','yes')
    items = storage.list_messages(limit=limit, q=q, offset=offset, saved=saved_bool)  # type: ignore
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
    _broadcast("deleted", id=int(mid))
    return _json({"ok": bool(ok)})

async def api_delete_all(request: web.Request):
    keep = request.rel_url.query.get('keep_saved')
    keep_saved = False
    if keep is not None:
        try:
            keep_saved = bool(int(keep))
        except Exception:
            keep_saved = keep.lower() in ('1','true','yes')
    n = storage.delete_all(keep_saved=keep_saved)  # type: ignore
    _broadcast("deleted_all", count=int(n), keep_saved=bool(keep_saved))
    return _json({"deleted": int(n), "keep_saved": bool(keep_saved)})

async def api_mark_read(request: web.Request):
    mid = int(request.match_info["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    read = bool(body.get("read", True))
    ok = storage.mark_read(mid, read)  # type: ignore
    if ok:
        _broadcast("marked", id=int(mid), read=bool(read))
    return _json({"ok": bool(ok)})

async def api_toggle_saved(request: web.Request):
    mid = int(request.match_info["id"])
    try:
        data = await request.json()
    except Exception:
        data = {}
    saved = bool(int(data.get("saved", 1))) if isinstance(data.get("saved", 1), (int, str)) else bool(data.get("saved", True))
    ok = storage.set_saved(mid, saved)  # type: ignore
    if ok:
        _broadcast("saved", id=int(mid), saved=bool(saved))
    return _json({"ok": bool(ok)})

async def api_get_settings(request: web.Request):
    days = storage.get_retention_days()  # type: ignore
    return _json({"retention_days": int(days)})

async def api_save_settings(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
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
    _broadcast("purged", days=int(days), deleted=int(n))
    return _json({"purged": int(n)})

# Optional backward-compat endpoint: forward to bot's internal wake server
async def api_wake(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    text = str(data.get("text") or "")
    # Save UI wake to inbox first
    mid = storage.save_message("UI Wake", text, "ui", 5, {})  # type: ignore
    _broadcast("created", id=int(mid))
    # Forward to bot
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://127.0.0.1:2599/internal/wake", json={"text": text}, timeout=10) as r:
                resp = await r.json()
    except Exception as e:
        resp = {"ok": False, "error": str(e)}
    return _json(resp)

# ----- App factory and routes -----
def _make_app() -> web.Application:
    app = web.Application()
    # API routes
    app.router.add_get("/api/stream", _sse)
    app.router.add_get("/api/messages", api_list_messages)
    app.router.add_post("/api/messages", api_create_message)
    app.router.add_get("/api/messages/{id:\\d+}", api_get_message)
    app.router.add_delete("/api/messages/{id:\\d+}", api_delete_message)
    app.router.add_delete("/api/messages", api_delete_all)  # ?keep_saved=1
    app.router.add_post("/api/messages/{id:\\d+}/read", api_mark_read)
    app.router.add_post("/api/messages/{id:\\d+}/save", api_toggle_saved)
    app.router.add_get("/api/inbox/settings", api_get_settings)
    app.router.add_post("/api/inbox/settings", api_save_settings)
    app.router.add_post("/api/inbox/purge", api_purge)
    app.router.add_post("/api/wake", api_wake)  # optional back-compat

    # Static UI from /app/www
    ui_root = _ui_root()
    idx = ui_root / "index.html"
    async def _index(_):
        if not idx.exists():
            return web.Response(text="UI missing (expected /app/www/index.html)", status=404)
        return web.FileResponse(path=str(idx))
    # Serve at / and /ui/
    app.router.add_get("/", _index)
    app.router.add_get("/ui/", _index)
    app.router.add_static("/ui/", str(ui_root))
    app.router.add_static("/", str(ui_root))
    return app

if __name__ == "__main__":
    port = int(os.getenv("INBOX_PORT", "2581"))
    web.run_app(_make_app(), host="0.0.0.0", port=port)
