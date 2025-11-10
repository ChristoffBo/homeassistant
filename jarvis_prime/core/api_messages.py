#!/usr/bin/env python3
import os, json, asyncio
from pathlib import Path
from aiohttp import web
import importlib.util

# ============================================================================
# LLM SAFETY PATCH - Add this before importing llm_client
# ============================================================================
def get_safe_llm_config():
    """
    Load LLM config with safety overrides applied.
    Returns: (ctx_tokens, should_load_llm, reason)
    """
    config_path = os.getenv("CONFIG_PATH", "/data/options.json")
    
    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception as e:
        print(f"[LLM Safety] Failed to load config: {e}")
        return 8192, False, "config_load_failed"
    
    llm_enabled = config.get("llm_enabled", False)
    
    # Check for emergency disable flag from run.sh
    if os.getenv("LLM_EMERGENCY_DISABLED") == "true":
        print("[LLM Safety] Emergency disable flag detected - LLM disabled by crash recovery")
        return 8192, False, "emergency_disabled"
    
    if not llm_enabled:
        return 8192, False, "disabled_in_config"
    
    ctx_tokens = config.get("llm_ctx_tokens", 8192)
    
    # Check for safety override from run.sh pre-flight checks
    safety_override_path = "/tmp/jarvis_safe_ctx"
    if os.path.exists(safety_override_path):
        try:
            with open(safety_override_path) as f:
                safe_ctx = int(f.read().strip())
                print(f"[LLM Safety] Pre-flight safety override active: {ctx_tokens} → {safe_ctx}")
                print(f"[LLM Safety] Reason: Insufficient memory detected during startup")
                ctx_tokens = safe_ctx
                # Clean up the override file
                os.remove(safety_override_path)
        except Exception as e:
            print(f"[LLM Safety] Failed to read safety override: {e}")
    
    # Hard safety limits regardless of config
    if ctx_tokens > 32768:
        print(f"[LLM Safety] Context {ctx_tokens} exceeds hard limit, capping at 32768")
        ctx_tokens = 32768
    elif ctx_tokens < 512:
        print(f"[LLM Safety] Context {ctx_tokens} too small, setting to 2048")
        ctx_tokens = 2048
    
    return ctx_tokens, True, "ok"

# Apply safety config before importing llm_client
safe_ctx, should_load, reason = get_safe_llm_config()
if should_load:
    # Override the config value with safe value
    try:
        config_path = os.getenv("CONFIG_PATH", "/data/options.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                config_data = json.load(f)
            
            # Only override if different to show what we did
            if config_data.get("llm_ctx_tokens") != safe_ctx:
                original_ctx = config_data.get("llm_ctx_tokens", "unset")
                print(f"[LLM Safety] Applying safe context: {original_ctx} → {safe_ctx}")
                # Set environment variable for llm_client to use
                os.environ["JARVIS_SAFE_CTX"] = str(safe_ctx)
    except Exception as e:
        print(f"[LLM Safety] Warning: Could not apply context override: {e}")
        # Continue anyway with defaults
else:
    print(f"[LLM Safety] LLM disabled: {reason}")
    os.environ["LLM_EMERGENCY_DISABLED"] = "true"

# ============================================================================
# END LLM SAFETY PATCH
# ============================================================================

# Import LLM client (it will read JARVIS_SAFE_CTX if set)
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
_BACKUP_MODULE_FILE = _THIS_DIR / "backup_module.py"
backup_module_spec = importlib.util.spec_from_file_location("jarvis_backup_module", str(_BACKUP_MODULE_FILE))
backup_module = importlib.util.module_from_spec(backup_module_spec)  # type: ignore
if backup_module_spec and backup_module_spec.loader and _BACKUP_MODULE_FILE.exists():
    try:
        backup_module_spec.loader.exec_module(backup_module)  # type: ignore
        print("[backup_module] Module loaded")
    except Exception as e:
        print(f"[backup_module] Failed to load: {e}")
        backup_module = None
else:
    backup_module = None
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
    if saved:
        msgs = storage.list_saved_messages(limit, offset)  # type: ignore
        total = len(msgs) if msgs else 0  # Fallback if count_messages not available
    elif q:
        msgs = storage.search_messages(q, limit, offset)  # type: ignore
        total = len(msgs) if msgs else 0  # Fallback if count_messages not available
    else:
        msgs = storage.list_messages(limit, offset)  # type: ignore
        total = len(msgs) if msgs else 0  # Fallback if count_messages not available
    
    # Try to use count_messages if available for accurate totals
    try:
        if hasattr(storage, 'count_messages'):
            if saved:
                total = storage.count_messages(saved=True)  # type: ignore
            elif q:
                total = storage.count_messages(search_query=q)  # type: ignore
            else:
                total = storage.count_messages()  # type: ignore
    except Exception:
        pass  # Use fallback total from len(msgs)
    
    return _json({"messages": msgs, "total": total, "limit": limit, "offset": offset})

async def api_get_message(request: web.Request):
    mid = request.match_info["id"]
    msg = storage.get_message(int(mid))  # type: ignore
    if not msg:
        return _json({"error": "not found"}, status=404)
    return _json(msg)

async def api_delete_message(request: web.Request):
    mid = request.match_info["id"]
    storage.delete_message(int(mid))  # type: ignore
    _broadcast("deleted", id=int(mid))
    return _json({"ok": True})

async def api_delete_all(request: web.Request):
    storage.delete_all_messages()  # type: ignore
    _broadcast("cleared")
    return _json({"ok": True})

async def api_mark_read(request: web.Request):
    mid = request.match_info["id"]
    storage.mark_read(int(mid))  # type: ignore
    _broadcast("updated", id=int(mid))
    return _json({"ok": True})

async def api_toggle_saved(request: web.Request):
    mid = request.match_info["id"]
    storage.toggle_saved(int(mid))  # type: ignore
    _broadcast("updated", id=int(mid))
    return _json({"ok": True})

async def api_get_settings(request: web.Request):
    s = storage.get_settings()  # type: ignore
    return _json(s)

async def api_save_settings(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    storage.save_settings(body)  # type: ignore
    return _json({"ok": True})

async def api_purge(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    hours = int(body.get("hours", 72))
    deleted_count = storage.purge_old_messages(hours)  # type: ignore
    _broadcast("purged")
    return _json({"ok": True, "deleted": deleted_count})

async def api_wake(request: web.Request):
    """POST /api/wake - wake orchestrator or trigger manual inbox run"""
    _broadcast("wake")
    return _json({"ok": True})

async def api_emit(request: web.Request):
    """POST /internal/emit - broadcast SSE event for internal modules"""
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    event = str(data.get("event", "custom"))
    payload = data.get("payload", {})
    _broadcast(event, **payload)
    
    return _json({"ok": True})

async def api_get_config(request: web.Request):
    """GET /api/config - returns current config"""
    is_hassio = bool(os.getenv("HASSIO_TOKEN"))
    
    if is_hassio:
        # Read from supervisor /data/options.json
        config_path = Path("/data/options.json")
    else:
        # Docker: Use JARVIS_CONFIG_PATH or default to /data/config.json
        config_path = Path(os.getenv("JARVIS_CONFIG_PATH", "/data/config.json"))
    
    config = {}
    
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except Exception as e:
            print(f"[config] Failed to read config from {config_path}: {e}")
    else:
        print(f"[config] Config file not found at {config_path}")
    
    return _json({
        "config": config,
        "is_hassio": is_hassio,
        "readonly": is_hassio
    })

async def api_save_config(request: web.Request):
    """POST /api/config - saves config (Docker only)"""
    is_hassio = bool(os.getenv("HASSIO_TOKEN"))
    
    if is_hassio:
        return _json({"error": "Use Home Assistant addon UI to configure"}, status=403)
    
    try:
        new_config = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    # Use JARVIS_CONFIG_PATH if set, otherwise default to /data/config.json
    config_path = Path(os.getenv("JARVIS_CONFIG_PATH", "/data/config.json"))
    
    try:
        config_path.write_text(json.dumps(new_config, indent=2))
        print(f"[config] Saved config to {config_path}")
        return _json({"ok": True, "restart_required": True})
    except Exception as e:
        print(f"[config] Failed to save config to {config_path}: {e}")
        return _json({"error": str(e)}, status=500)

# ---- LLM API ----
async def api_llm_rewrite(request: web.Request):
    """POST /api/llm/rewrite - submit rewrite task"""
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    text = str(data.get("text", ""))
    if not text:
        return _json({"error": "text required"}, status=400)
    
    mood = str(data.get("mood", "neutral"))
    timeout = int(data.get("timeout", 12))
    
    task_id = llm_client.submit_task(
        llm_client.rewrite,
        text=text,
        mood=mood,
        timeout=timeout,
        allow_profanity=False
    )
    
    return _json({"task_id": task_id, "status": "processing"})

async def api_llm_riff(request: web.Request):
    """POST /api/llm/riff - submit persona riff task"""
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    persona = str(data.get("persona", "neutral"))
    context = str(data.get("context", ""))
    max_lines = int(data.get("max_lines", 3))
    timeout = int(data.get("timeout", 8))
    
    task_id = llm_client.submit_task(
        llm_client.persona_riff,
        persona=persona,
        context=context,
        max_lines=max_lines,
        timeout=timeout
    )
    
    return _json({"task_id": task_id, "status": "processing"})

async def api_llm_chat(request: web.Request):
    """POST /api/llm/chat - submit chat task"""
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "bad json"}, status=400)
    
    messages = data.get("messages", [])
    if not messages:
        return _json({"error": "messages required"}, status=400)
    
    system_prompt = str(data.get("system_prompt", ""))
    max_tokens = int(data.get("max_tokens", 384))
    timeout = int(data.get("timeout", 20))
    
    task_id = llm_client.submit_task(
        llm_client.chat_generate,
        messages=messages,
        system_prompt=system_prompt,
        max_new_tokens=max_tokens,
        timeout=timeout
    )
    
    return _json({"task_id": task_id, "status": "processing"})

async def api_llm_task_status(request: web.Request):
    """GET /api/llm/task/{task_id} - get task status"""
    task_id = request.match_info["task_id"]
    status = llm_client.get_task_status(task_id)
    return _json(status)

# ---- app ----
def _make_app() -> web.Application:
    app = web.Application()
    
    # Startup hook to start orchestrator scheduler, analytics monitors, and sentinel monitors after event loop is running
    async def start_background_tasks(app):
        if orchestrator_module:
            orchestrator_module.start_orchestrator_scheduler()
        if analytics_module:
            await analytics_module.init_analytics(app, notification_callback=notify_via_analytics)
            print("[analytics] Initialized and monitoring started")
        if sentinel_instance:
            sentinel_instance.start_all_monitoring()
            asyncio.create_task(sentinel_instance.auto_purge())
            print("[sentinel] Monitoring started")

    app.on_startup.append(start_background_tasks)
    
    # ✅ Ensure Atlas routes are registered before startup (fixes 404)
    if atlas_module:
       atlas_module.register_routes(app)
       print("[atlas] Routes registered (pre-startup)")
 
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
    
    # Config API
    app.router.add_get("/api/config", api_get_config)
    app.router.add_post("/api/config", api_save_config)

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

    # Register backup_module routes if available
    if backup_module:
        try:
            if hasattr(backup_module, 'setup_routes'):
                backup_module.setup_routes(app)
                print("[backup_module] Routes registered via setup_routes()")
            elif hasattr(backup_module, 'register_routes'):
                backup_module.register_routes(app)
                print("[backup_module] Routes registered via register_routes()")
            else:
                print("[backup_module] No route registration function found")
        except Exception as e:
            print(f"[backup_module] Failed to register routes: {e}")

    # Register backup routes if available (old backup.py)
    try:
        from backup import register_routes as register_backup
        register_backup(app)
        print("[backup] Routes registered")
    except Exception as e:
        print(f"[backup] Failed to register routes: {e}")

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

    return app

if __name__ == "__main__":
    port = int(os.getenv("INBOX_PORT", "2581"))
    web.run_app(_make_app(), host="0.0.0.0", port=port)