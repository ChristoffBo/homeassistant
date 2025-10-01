#!/usr/bin/env python3
import os, json, asyncio
from pathlib import Path
from aiohttp import web
import importlib.util

_THIS_DIR = Path(__file__).resolve().parent

# ---- storage ----
_STORAGE_FILE = _THIS_DIR / "storage.py"
spec = importlib.util.spec_from_file_location("jarvis_storage", str(_STORAGE_FILE))
storage = importlib.util.module_from_spec(spec)  # type: ignore
assert spec and spec.loader, "Cannot load storage.py"
spec.loader.exec_module(storage)  # type: ignore
storage.init_db(os.getenv("JARVIS_DB_PATH", "/data/jarvis.db"))

# ---- orchestrator ----
_ORCHESTRATOR_FILE = _THIS_DIR / "orchestrator.py"
orchestrator_spec = importlib.util.spec_from_file_location("jarvis_orchestrator", str(_ORCHESTRATOR_FILE))
orchestrator_module = importlib.util.module_from_spec(orchestrator_spec)  # type: ignore
if orchestrator_spec and orchestrator_spec.loader and _ORCHESTRATOR_FILE.exists():
    orchestrator_spec.loader.exec_module(orchestrator_module)  # type: ignore
    
    def notify_via_inbox(data):
        """Send orchestrator notifications through inbox"""
        title = data.get("title", "Orchestrator")
        message = data.get("message", "")
        priority = 8 if data.get("priority") == "high" else 5
        storage.save_message(title, message, "orchestrator", priority, {})  # type: ignore
        _broadcast("created")
    
    orchestrator_module.init_orchestrator(
        config={
            "playbooks_path": "/share/jarvis_prime/playbooks",
            "runner": "ansible"  # or "script" if you don't want Ansible
        },
        db_path=os.getenv("JARVIS_DB_PATH", "/data/jarvis.db"),
        notify_callback=notify_via_inbox,
        logger=print
    )
    print("[orchestrator] Initialized")
else:
    orchestrator_module = None
    print("[orchestrator] Not found or failed to load")

# ---- choose ONE UI root ----
CANDIDATES = [
    Path("/share/jarvis_prime/ui"),
    Path("/app/www"),
    Path("/app/ui"),
    _THIS_DIR,
]

def pick_ui_root():
    for d in CANDIDATES:
        idx = d / "index.html"
        if d.is_dir() and idx.exists():
            return d, idx
    # last resort: first existing dir even if index missing
    for d in CANDIDATES:
        if d.is_dir():
            return d, d / "index.html"
    return Path("/app/www"), Path("/app/www/index.html")

UI_ROOT, UI_INDEX = pick_ui_root()
print(f"[inbox] UI root: {UI_ROOT} (index={UI_INDEX.exists()})")

# ---- SSE ----
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
    try:
        await resp.write(b": hello\n\n")
    except Exception:
        pass
    try:
        while True:
            data = await q.get()
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            try:
                await resp.write(b"data: " + payload + b"\n\n")
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

def _json(data, status=200):
    return web.Response(text=json.dumps(data, ensure_ascii=False), status=status, content_type="application/json")

# ---- API ----
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

# UI wake passthrough -> bot internal wake
async def api_wake(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    text = str(data.get("text") or "")
    mid = storage.save_message("Wake", text, "ui", 5, {})  # type: ignore
    _broadcast("created", id=int(mid))
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://127.0.0.1:2599/internal/wake", json={"text": text}, timeout=10) as r:
                ok = (r.status == 200)
                try:
                    body = await r.json()
                    if isinstance(body, dict) and "ok" in body:
                        ok = bool(body["ok"])
                except Exception:
                    pass
    except Exception as e:
        return _json({"ok": False, "error": str(e)})
    return _json({"ok": ok})

# NEW: UI emit passthrough -> bot internal emit
async def api_emit(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://127.0.0.1:2599/internal/emit", json=data, timeout=10) as r:
                body = await r.text()
                try:
                    parsed = json.loads(body)
                except Exception:
                    parsed = {"raw": body}
                return _json(parsed, status=r.status)
    except Exception as e:
        return _json({"ok": False, "error": str(e)}, status=500)

# ---- app ----
def _make_app() -> web.Application:
    app = web.Application()
    
    # Startup hook to start orchestrator scheduler after event loop is running
    async def start_background_tasks(app):
        if orchestrator_module:
            orchestrator_module.start_orchestrator_scheduler()
    
    app.on_startup.append(start_background_tasks)
    
    # API routes
    app.router.add_get("/api/stream", _sse)
    app.router.add_get("/api/messages", api_list_messages)
    app.router.add_post("/api/messages", api_create_message)
    app.router.add_get("/api/messages/{id:\\d+}", api_get_message)
    app.router.add_delete("/api/messages/{id:\\d+}", api_delete_message)
    app.router.add_delete("/api/messages", api_delete_all)
    app.router.add_post("/api/messages/{id:\\d+}/read", api_mark_read)
    app.router.add_post("/api/messages/{id:\\d+}/save", api_toggle_saved)
    app.router.add_get("/api/inbox/settings", api_get_settings)
    app.router.add_post("/api/inbox/settings", api_save_settings)
    app.router.add_post("/api/inbox/purge", api_purge)
    app.router.add_post("/api/wake", api_wake)
    app.router.add_post("/internal/wake", api_wake)
    app.router.add_post("/internal/emit", api_emit)

    # Register orchestrator routes if available
    if orchestrator_module:
        orchestrator_module.register_routes(app)

    # ONE static root only
    async def _index(_):
        if UI_INDEX.exists():
            return web.FileResponse(path=str(UI_INDEX))
        return web.Response(text="UI index.html missing in " + str(UI_ROOT), status=404)

    app.router.add_get("/", _index)
    app.router.add_get("/ui/", _index)
    app.router.add_static("/ui/", str(UI_ROOT))
    app.router.add_static("/", str(UI_ROOT))

    # diagnostics
    async def _debug_ui_root(_):
        return _json({"ui_root": str(UI_ROOT), "index_exists": UI_INDEX.exists()})
    app.router.add_get("/debug/ui-root", _debug_ui_root)

    return app

if __name__ == "__main__":
    port = int(os.getenv("INBOX_PORT", "2581"))
    web.run_app(_make_app(), host="0.0.0.0", port=port)
