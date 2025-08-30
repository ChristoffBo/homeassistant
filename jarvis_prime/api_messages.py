#!/usr/bin/env python3
# api_messages.py — REST API for Jarvis Prime inbox
# Exposes:
#   GET  /api/messages?limit=50&q=...
#   GET  /api/messages/{id}
#   POST /api/messages/{id}/read   {"read": true}
#   DELETE /api/messages/{id}
#   GET  /api/inbox/settings
#   PUT  /api/inbox/settings       {"retention_days": 30}
#   PATCH /api/inbox/settings      {"retention_days": 30}
#   POST /api/messages/purge       {"days": 30}   # optional
#
# Also serves /ui static (index.html) if present alongside this file.

from __future__ import annotations
import os, json, asyncio
from aiohttp import web
import storage

API_BIND = os.getenv("JARVIS_API_BIND", "0.0.0.0")
API_PORT = int(os.getenv("JARVIS_API_PORT", "2581"))
DB_PATH  = os.getenv("JARVIS_DB_PATH", "/data/jarvis.db")
UI_DIR   = os.getenv("JARVIS_UI_DIR", os.path.join(os.path.dirname(__file__), "ui"))

# ------------- Middleware: basic CORS + JSON errors -------------
@web.middleware
async def cors_middleware(request, handler):
    try:
        resp = await handler(request)
    except web.HTTPException as e:
        resp = web.json_response({"error": e.reason}, status=e.status)
    except Exception as e:
        resp = web.json_response({"error": str(e)}, status=500)
    # Allow local UI access
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
    try:
        limit = int(request.rel_url.query.get("limit", "50"))
    except Exception:
        limit = 50
    try:
        offset = int(request.rel_url.query.get("offset", "0"))
    except Exception:
        offset = 0
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
        app.router.add_static("/ui/", path=UI_DIR, name="ui", show_index=True)
        # Redirect /ui -> /ui/index.html
        async def _redir(request): 
            raise web.HTTPFound("/ui/index.html")
        app.router.add_get("/ui", _redir)
    return app

def run():
    app = create_app()
    web.run_app(app, host=API_BIND, port=API_PORT)

if __name__ == "__main__":
    run()
