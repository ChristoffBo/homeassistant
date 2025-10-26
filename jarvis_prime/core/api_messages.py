#!/usr/bin/env python3
import os, json, asyncio
from pathlib import Path
from aiohttp import web
import importlib.util

# Import LLM client
import llm_client
import auth

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

# ---- analytics ----
_ANALYTICS_FILE = _THIS_DIR / "analytics.py"
analytics_spec = importlib.util.spec_from_file_location("jarvis_analytics", str(_ANALYTICS_FILE))
analytics_module = importlib.util.module_from_spec(analytics_spec)  # type: ignore
if analytics_spec and analytics_spec.loader and _ANALYTICS_FILE.exists():
    analytics_spec.loader.exec_module(analytics_module)  # type: ignore

    def notify_via_analytics(source: str, level: str, message: str):
        """Send analytics service UP/DOWN events through inbox + broadcasts"""
        title = f"Analytics: {source}"
        body = f"{level.upper()}: {message}"
        priority = 8 if level.lower() in ["down", "critical", "error"] else 5
        storage.save_message(title, body, "analytics", priority, {})  # type: ignore
        _broadcast("created")

    print("[analytics] Module loaded")
else:
    analytics_module = None
    print("[analytics] Not found or failed to load")

# ---- sentinel ----
_SENTINEL_FILE = _THIS_DIR / "sentinel.py"
sentinel_spec = importlib.util.spec_from_file_location("jarvis_sentinel", str(_SENTINEL_FILE))
sentinel_module = importlib.util.module_from_spec(sentinel_spec)  # type: ignore
sentinel_instance = None
if sentinel_spec and sentinel_spec.loader and _SENTINEL_FILE.exists():
    try:
        sentinel_spec.loader.exec_module(sentinel_module)  # type: ignore
        
        def notify_via_sentinel(title, body, source="sentinel", priority=5):
            """Send sentinel health/recovery events through inbox"""
            storage.save_message(title, body, source, priority, {})  # type: ignore
            _broadcast("created")
        
        sentinel_instance = sentinel_module.Sentinel(
            config={
                "data_path": "/share/jarvis_prime/sentinel"
            },
            db_path=os.getenv("JARVIS_DB_PATH", "/data/jarvis.db"),
            notify_callback=notify_via_sentinel,
            logger_func=print
        )
        print("[sentinel] Initialized")
    except Exception as e:
        print(f"[sentinel] Failed to initialize: {e}")
        sentinel_instance = None
else:
    sentinel_module = None
    sentinel_instance = None
    print("[sentinel] Not found or failed to load")

# ---- atlas ----
_ATLAS_FILE = _THIS_DIR / "atlas.py"
atlas_spec = importlib.util.spec_from_file_location("jarvis_atlas", str(_ATLAS_FILE))
atlas_module = importlib.util.module_from_spec(atlas_spec)  # type: ignore
if atlas_spec and atlas_spec.loader and _ATLAS_FILE.exists():
    atlas_spec.loader.exec_module(atlas_module)  # type: ignore
    print("[atlas] Initialized")
else:
    atlas_module = None
    print("[atlas] Not found or failed to load")

# ---- backup_module ----
_BACKUP_FILE = _THIS_DIR / "backup_module.py"
backup_spec = importlib.util.spec_from_file_location("jarvis_backup", str(_BACKUP_FILE))
backup_module = importlib.util.module_from_spec(backup_spec)  # type: ignore
backup_manager = None
if backup_spec and backup_spec.loader and _BACKUP_FILE.exists():
    try:
        backup_spec.loader.exec_module(backup_module)  # type: ignore
        
        def notify_via_backup(title, body, source="backup", priority=5):
            """Send backup notifications through inbox"""
            storage.save_message(title, body, source, priority, {})  # type: ignore
            _broadcast("created")
        
        backup_manager = backup_module.BackupManager(
            config_path="/share/jarvis_prime/backup",
            notify_callback=notify_via_backup,
            logger=print
        )
        print("[backup_module] Loaded")
    except Exception as e:
        print(f"[backup_module] Failed to initialize: {e}")
        backup_manager = None
else:
    backup_module = None
    backup_manager = None
    print("[backup_module] Not found or failed to load")

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
    items = storage.get_all_messages()  # type: ignore
    return _json({"items": items})

async def api_delete_message(request: web.Request):
    mid = request.match_info.get("id")
    if not mid:
        return _json({"error":"no id"}, status=400)
    storage.delete_message(int(mid))  # type: ignore
    _broadcast("deleted", id=int(mid))
    return _json({"ok": True})

async def api_save_message(request: web.Request):
    mid = request.match_info.get("id")
    if not mid:
        return _json({"error":"no id"}, status=400)
    storage.toggle_save(int(mid))  # type: ignore
    _broadcast("saved", id=int(mid))
    return _json({"ok": True})

async def api_delete_all(request: web.Request):
    qs = request.rel_url.query
    keep_saved = (qs.get("keep_saved") == "1")
    storage.delete_all_messages(keep_saved=keep_saved)  # type: ignore
    _broadcast("deleted_all")
    return _json({"ok": True})

async def api_save_settings(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return _json({"error":"bad json"}, status=400)
    # For inbox settings, just acknowledge - storage handles it internally if needed
    return _json({"ok": True})

async def api_purge(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return _json({"error":"bad json"}, status=400)
    days = int(data.get("days", 7))
    storage.purge_old_messages(days)  # type: ignore
    _broadcast("purged")
    return _json({"ok": True})

# ---- LLM task queue ----
llm_tasks = {}
llm_task_counter = 0

async def api_llm_rewrite(request: web.Request):
    global llm_task_counter
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)

    text = data.get("text", "")
    style = data.get("style", "improved")
    max_tokens = int(data.get("max_tokens", 256))
    timeout = int(data.get("timeout", 20))

    llm_task_counter += 1
    task_id = f"rewrite-{llm_task_counter}"

    async def _run():
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(llm_client.rewrite_text, text, style, max_tokens),
                timeout=timeout
            )
            llm_tasks[task_id] = {"status": "complete", "result": result}
        except asyncio.TimeoutError:
            llm_tasks[task_id] = {"status": "error", "error": "Timeout"}
        except Exception as e:
            llm_tasks[task_id] = {"status": "error", "error": str(e)}

    llm_tasks[task_id] = {"status": "processing"}
    asyncio.create_task(_run())
    return _json({"task_id": task_id})

async def api_llm_riff(request: web.Request):
    global llm_task_counter
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)

    prompt = data.get("prompt", "")
    max_tokens = int(data.get("max_tokens", 100))
    timeout = int(data.get("timeout", 20))

    llm_task_counter += 1
    task_id = f"riff-{llm_task_counter}"

    async def _run():
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(llm_client.persona_riff, prompt, max_tokens),
                timeout=timeout
            )
            llm_tasks[task_id] = {"status": "complete", "result": result}
        except asyncio.TimeoutError:
            llm_tasks[task_id] = {"status": "error", "error": "Timeout"}
        except Exception as e:
            llm_tasks[task_id] = {"status": "error", "error": str(e)}

    llm_tasks[task_id] = {"status": "processing"}
    asyncio.create_task(_run())
    return _json({"task_id": task_id})

async def api_llm_chat(request: web.Request):
    global llm_task_counter
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)

    messages = data.get("messages", [])
    max_tokens = int(data.get("max_tokens", 384))
    timeout = int(data.get("timeout", 20))

    llm_task_counter += 1
    task_id = f"chat-{llm_task_counter}"

    async def _run():
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(llm_client.chat, messages, max_tokens),
                timeout=timeout
            )
            llm_tasks[task_id] = {"status": "complete", "result": result}
        except asyncio.TimeoutError:
            llm_tasks[task_id] = {"status": "error", "error": "Timeout"}
        except Exception as e:
            llm_tasks[task_id] = {"status": "error", "error": str(e)}

    llm_tasks[task_id] = {"status": "processing"}
    asyncio.create_task(_run())
    return _json({"task_id": task_id})

async def api_llm_task_status(request: web.Request):
    task_id = request.match_info.get("task_id")
    if not task_id or task_id not in llm_tasks:
        return _json({"status": "not_found"}, status=404)
    return _json(llm_tasks[task_id])

def _make_app():
    app = web.Application()

    # Message API routes
    app.router.add_get("/api/stream", _sse)
    app.router.add_post("/api/messages", api_create_message)
    app.router.add_get("/api/messages", api_list_messages)
    app.router.add_delete("/api/messages/{id}", api_delete_message)
    app.router.add_post("/api/messages/{id}/save", api_save_message)
    app.router.add_delete("/api/messages", api_delete_all)
    app.router.add_post("/api/inbox/settings", api_save_settings)
    app.router.add_post("/api/inbox/purge", api_purge)

    # LLM routes
    app.router.add_post("/api/llm/rewrite", api_llm_rewrite)
    app.router.add_post("/api/llm/riff", api_llm_riff)
    app.router.add_post("/api/llm/chat", api_llm_chat)
    app.router.add_get("/api/llm/task/{task_id}", api_llm_task_status)

    # Register orchestrator routes if available
    if orchestrator_module:
        orchestrator_module.register_routes(app)

    # Register analytics routes if available
    if analytics_module:
        analytics_module.register_routes(app)
        print("[analytics] Routes registered")

    # Register sentinel routes if available
    if sentinel_instance:
        sentinel_instance.setup_routes(app)
        print("[sentinel] Routes registered")

    # Register atlas routes if available
    if atlas_module and hasattr(atlas_module, 'register_routes'):
        atlas_module.register_routes(app)
        print("[atlas] Routes registered")

    # Register backup routes if available
    if backup_module and hasattr(backup_module, 'setup_routes'):
        backup_module.setup_routes(app)
        print("[backup_module] Routes registered")

    # Register authentication routes
    try:
        auth.setup_auth_routes(app)
        print("[auth] Routes registered")
    except Exception as e:
        print(f"[auth] Failed to register routes: {e}")

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

    # Startup hook for modules
    async def on_startup(app):
        if analytics_module and hasattr(analytics_module, 'start_monitoring'):
            asyncio.create_task(analytics_module.start_monitoring())
            print("[analytics] Initialized and monitoring started")
        
        if sentinel_instance and hasattr(sentinel_instance, 'start'):
            asyncio.create_task(sentinel_instance.start())
            print("[sentinel] Monitoring started")
        
        if backup_manager and hasattr(backup_manager, 'start'):
            await backup_manager.start()
            print("[backup_module] Initialized and started")

    async def on_cleanup(app):
        if backup_manager and hasattr(backup_manager, 'shutdown'):
            await backup_manager.shutdown()
            print("[backup_module] Shutdown complete")

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app

if __name__ == "__main__":
    port = int(os.getenv("INBOX_PORT", "2581"))
    web.run_app(_make_app(), host="0.0.0.0", port=port)
