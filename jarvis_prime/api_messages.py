#!/usr/bin/env python3
from __future__ import annotations

import os
import json
from typing import Any, Dict, List
from aiohttp import web
import aiohttp

# Local storage module (already present in the project)
import storage

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
API_BIND = os.getenv("JARVIS_API_BIND", "0.0.0.0")
API_PORT = int(os.getenv("JARVIS_API_PORT", "2581"))
DB_PATH  = os.getenv("JARVIS_DB_PATH", "/data/jarvis.db")

# UI can be overridden via host share; otherwise serve the built-in UI
DEFAULT_UI_DIR = os.path.join(os.path.dirname(__file__), "ui")
UI_DIR = os.getenv("JARVIS_UI_DIR", DEFAULT_UI_DIR)

# Make sure storage knows where to create/open the DB if it reads env
os.environ.setdefault("JARVIS_DB_PATH", DB_PATH)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _ok(data: Dict[str, Any] | List[Any] | None = None) -> web.Response:
    return web.json_response(data if data is not None else {"ok": True})

def _bad_request(msg: str) -> web.Response:
    return web.json_response({"error": msg}, status=400)


# -------------------------------------------------------------------
# API Handlers
# -------------------------------------------------------------------
async def handle_options(request: web.Request) -> web.Response:
    # Simple CORS-friendly empty 204
    return web.Response(status=204)

async def api_list_messages(request: web.Request) -> web.Response:
    q = request.rel_url.query.get("q") or None
    try:
        limit = int(request.rel_url.query.get("limit", "50"))
        offset = int(request.rel_url.query.get("offset", "0"))
    except ValueError:
        return _bad_request("limit/offset must be integers")

    items = storage.list_messages(limit=limit, q=q, offset=offset)
    return _ok({"items": items})

async def api_get_message(request: web.Request) -> web.Response:
    try:
        mid = int(request.match_info["id"])
    except Exception:
        return _bad_request("invalid id")

    item = storage.get_message(mid)
    if not item:
        raise web.HTTPNotFound(text="message not found")
    return _ok(item)

async def api_delete_message(request: web.Request) -> web.Response:
    try:
        mid = int(request.match_info["id"])
    except Exception:
        return _bad_request("invalid id")

    ok = storage.delete_message(mid)
    if not ok:
        raise web.HTTPNotFound(text="message not found")
    return _ok({"deleted": mid})

async def api_mark_read(request: web.Request) -> web.Response:
    try:
        mid = int(request.match_info["id"])
    except Exception:
        return _bad_request("invalid id")

    try:
        data = await request.json()
    except Exception:
        data = {}
    read = bool(data.get("read", True))

    ok = storage.mark_read(mid, read=read)
    if not ok:
        raise web.HTTPNotFound(text="message not found")
    return _ok({"id": mid, "read": read})

async def api_get_settings(request: web.Request) -> web.Response:
    days = storage.get_retention_days()
    return _ok({"retention_days": int(days)})

async def api_put_settings(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        days = int(data.get("retention_days"))
    except Exception:
        return _bad_request("retention_days must be an integer")
    storage.set_retention_days(days)
    return _ok({"retention_days": days})

async def api_purge(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        days = int(data.get("days"))
    except Exception:
        # default to current retention days if not provided
        days = int(storage.get_retention_days())
    removed = storage.purge_older_than(days)
    return _ok({"removed": int(removed), "days": int(days)})


# -------------------------------------------------------------------
# UI Handlers
# -------------------------------------------------------------------
async def ui_index(request: web.Request) -> web.StreamResponse:
    """Serve the SPA entry file for both /ui and /ui/. """
    index_path = os.path.join(UI_DIR, "index.html")
    if not os.path.exists(index_path):
        raise web.HTTPNotFound(text="index.html missing in UI directory")
    return web.FileResponse(index_path)


# -------------------------------------------------------------------
# App Factory
# -------------------------------------------------------------------
def create_app() -> web.Application:
    # Initialize DB (storage reads path from env)
    try:
        storage.init_db()  # takes no positional args in this project
    except TypeError:
        # In case an older variant expects a path, try it
        try:
            storage.init_db(DB_PATH)  # type: ignore
        except Exception:
            raise

    app = web.Application()

    # CORS preflight fallback
    app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)

    # API routes
    app.router.add_get("/api/messages", api_list_messages)
    app.router.add_get("/api/messages/{id}", api_get_message)
    app.router.add_delete("/api/messages/{id}", api_delete_message)
    app.router.add_post("/api/messages/{id}/read", api_mark_read)
    app.router.add_get("/api/inbox/settings", api_get_settings)
    app.router.add_put("/api/inbox/settings", api_put_settings)
    app.router.add_post("/api/messages/purge", api_purge)

    # UI routes (no directory listing; always serve index for /ui and /ui/)
    app.router.add_get("/ui", ui_index)
    app.router.add_get("/ui/", ui_index)
    app.router.add_static("/ui/", path=UI_DIR, name="ui", show_index=False)

    # Optional root redirect to /ui/
    async def root_redirect(request: web.Request) -> web.Response:
        raise web.HTTPFound("/ui/")

    app.router.add_get("/", root_redirect)

    return app


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def run() -> None:
    app = create_app()
    web.run_app(app, host=API_BIND, port=API_PORT)

if __name__ == "__main__":
    run()
