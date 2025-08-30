#!/usr/bin/env python3
# api_messages.py — REST API for Jarvis Prime inbox
# Adds passive Gotify mirror: if GOTIFY_URL + GOTIFY_CLIENT_TOKEN are present,
# it tails /stream and stores messages automatically.

from __future__ import annotations
import os, json, asyncio, aiohttp, time
from aiohttp import web
import storage

API_BIND = os.getenv("JARVIS_API_BIND", "0.0.0.0")
API_PORT = int(os.getenv("JARVIS_API_PORT", "2581"))
DB_PATH  = os.getenv("JARVIS_DB_PATH", "/data/jarvis.db")
UI_DIR   = os.getenv("JARVIS_UI_DIR", os.path.join(os.path.dirname(__file__), "ui"))

GOTIFY_URL = os.getenv("GOTIFY_URL", "")
GOTIFY_CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
NTFY_URL = os.getenv('NTFY_URL','')
NTFY_TOPIC = os.getenv('NTFY_TOPIC','')
NTFY_TOKEN = os.getenv('NTFY_TOKEN','')
NTFY_USER = os.getenv('NTFY_USER','')
NTFY_PASS = os.getenv('NTFY_PASS','')

# ------------- Middleware: basic CORS + JSON errors -------------
@web.middleware
async def cors_middleware(request, handler):
    try:
        resp = await handler(request)
    except web.HTTPException as e:
        resp = web.json_response({"error": e.reason}, status=e.status)
    except Exception as e:
        resp = web.json_response({"error": str(e)}, status=500)
    if isinstance(resp, web.StreamResponse):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return resp

async def handle_options(request):
    return web.Response(status=204)

# ------------- Routes ------------------------------------------
async def get_messages(request: web.Request):
    q = request.rel_url.query.get("q") or None
    try:    limit = int(request.rel_url.query.get("limit", "50"))
    except: limit = 50
    try:    offset = int(request.rel_url.query.get("offset", "0"))
    except: offset = 0
    items = storage.list_messages(limit=limit, q=q, offset=offset)
    return web.json_response({"items": items})

async def get_message(request: web.Request):
    mid = int(request.match_info["id"])
    item = storage.get_message(mid)
    if not item:
        raise web.HTTPNotFound()
    return web.json_response(item)

async def post_read(request: web.Request):
    mid = int(request.match_info["id"])
    data = await request.json(loads=json.loads)
    read = bool(data.get("read", True))
    ok = storage.mark_read(mid, read=read)
    if not ok:
        raise web.HTTPNotFound()
    return web.json_response({"ok": True, "id": mid, "read": read})

async def delete_message(request: web.Request):
    mid = int(request.match_info["id"])
    ok = storage.delete_message(mid)
    if not ok:
        raise web.HTTPNotFound()
    return web.json_response({"ok": True, "id": mid})

async def get_settings(request: web.Request):
    return web.json_response({"retention_days": storage.get_retention_days()})

async def put_settings(request: web.Request):
    data = await request.json(loads=json.loads)
    days = int(data.get("retention_days", storage.get_retention_days()))
    storage.set_retention_days(days)
    return web.json_response({"ok": True, "retention_days": storage.get_retention_days()})

async def post_purge(request: web.Request):
    try:
        data = await request.json(loads=json.loads)
    except Exception:
        data = {}
    days = int(data.get("days", storage.get_retention_days()))
    removed = storage.purge_older_than(days)
    return web.json_response({"ok": True, "removed": removed, "days": days})

# ------------- Background Gotify & ntfy stream mirror ------------------
async def mirror_gotify(app: web.Application):
    if not GOTIFY_URL or not GOTIFY_CLIENT_TOKEN:
        return  # no-op
    url = GOTIFY_URL.rstrip('/') + "/stream?token=" + GOTIFY_CLIENT_TOKEN
    while True:
        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as r:
                    # Server-Sent Events: read line-by-line
                    buf = []
                    async for raw in r.content:
                        line = raw.decode("utf-8", "ignore").rstrip()
                        if line.startswith("data:"):
                            payload = line[5:].strip()
                            try:
                                obj = json.loads(payload)
                                title = obj.get("title") or ""
                                message = obj.get("message") or ""
                                priority = obj.get("priority", 5)
                                ts = int(obj.get("date", time.time()))
                                meta = {"priority": priority, "via": "gotify-stream"}
                                delivered = {"gotify": {"status": 200}}
                                storage.save_message("gotify", title, message, meta=meta, delivered=delivered, ts=ts)
                            except Exception:
                                pass
                        # ignore other SSE lines (event:, id:, etc.)
        except Exception:
            await asyncio.sleep(5)  # reconnect backoff and continue

async def on_startup(app: web.Application):
    app["mirror_task"] = asyncio.create_task(mirror_gotify(app))

async def on_cleanup(app: web.Application):
    task = app.get("mirror_task")
    if task:
        task.cancel()
        try: await task
        except Exception: pass
    task2 = app.get('mirror_ntfy_task')
    if task2:
        task2.cancel()
        try: await task2
        except Exception: pass

def create_app() -> web.Application:
    storage.init_db(DB_PATH)
    app = web.Application(middlewares=[cors_middleware])
    # API
    app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    app.router.add_get   ("/api/messages",          get_messages)
    app.router.add_get   ("/api/messages/{id}",     get_message)
    app.router.add_post  ("/api/messages/{id}/read",post_read)
    app.router.add_delete("/api/messages/{id}",     delete_message)
    app.router.add_get   ("/api/inbox/settings",    get_settings)
    app.router.add_put   ("/api/inbox/settings",    put_settings)
    app.router.add_patch ("/api/inbox/settings",    put_settings)
    app.router.add_post  ("/api/messages/purge",    post_purge)
    # Static UI (served if present)
    if os.path.isdir(UI_DIR):
        app.router.add_static("/ui/", path=UI_DIR, name="ui", show_index=False)
                async def _index(request):
            return web.FileResponse(os.path.join(UI_DIR, "index.html"))
        app.router.add_get("/ui", _index)
        app.router.add_get("/ui/", _index)
    # background mirror
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

def run():
    app = create_app()
    web.run_app(app, host=API_BIND, port=API_PORT)

if __name__ == "__main__":
    run()

async def mirror_ntfy(app: web.Application):
    # ntfy has SSE at /<topic>/sse (self-hosted) or /v1/events?topic=... (ntfy.sh)
    if not NTFY_URL or not NTFY_TOPIC:
        return
    # prefer ntfy.sh style first
    urls = []
    base = NTFY_URL.rstrip('/')
    urls.append(f"{base}/v1/events?topic={NTFY_TOPIC}")
    urls.append(f"{base}/{NTFY_TOPIC}/sse")
    import aiohttp, base64, json, time
    headers = {}
    if NTFY_TOKEN:
        headers['Authorization'] = f"Bearer {NTFY_TOKEN}"
    elif NTFY_USER and NTFY_PASS:
        tok = base64.b64encode(f"{NTFY_USER}:{NTFY_PASS}".encode('utf-8')).decode('ascii')
        headers['Authorization'] = "Basic " + tok
    while True:
        for url in urls:
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    async with sess.get(url, headers=headers) as r:
                        async for raw in r.content:
                            line = raw.decode('utf-8','ignore').strip()
                            if not line or not line.startswith('{'):
                                continue
                            try:
                                evt = json.loads(line)
                            except Exception:
                                continue
                            # ntfy event has 'message' or 'title' depending on variant
                            title = evt.get('title') or evt.get('topic') or 'ntfy'
                            msg = evt.get('message') or evt.get('event') or ''
                            priority = int(evt.get('priority', 3))
                            meta = {'priority': priority, 'via': 'ntfy-stream'}
                            delivered = {'ntfy': {'status': 200}}
                            try:
                                import storage
                                storage.save_message('ntfy', title, msg, meta=meta, delivered=delivered)
                            except Exception:
                                pass
            except Exception:
                await asyncio.sleep(5)
