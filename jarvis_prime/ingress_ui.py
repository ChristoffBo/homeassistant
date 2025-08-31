#!/usr/bin/env python3
"""
ingress_ui.py — Add-on helper to make Home Assistant Ingress work without adding another server.

Usage (in your existing aiohttp app file, e.g. api_messages.py):
    from ingress_ui import wire_ingress_ui
    app = web.Application(...)
    wire_ingress_ui(app, ui_dir="/app/www")  # folder containing index.html and assets

What it does:
- Serves index.html for both "/" and "/ui/" (directory paths, with trailing slash)
- Serves static assets from ui_dir at "/ui" (so relative links like "logo.png" work)
- Normalizes paths so requests to "/ui" become "/ui/" (HA often calls the directory)
- Keeps all routes within the SAME aiohttp app (no extra server/process)
"""
import os
from aiohttp import web

def wire_ingress_ui(app: web.Application, ui_dir: str = "/app/www") -> None:
    ui_dir = os.path.abspath(ui_dir)
    os.makedirs(ui_dir, exist_ok=True)

    # Ensure missing trailing slash is corrected ("/ui" -> "/ui/")
    norm = web.normalize_path_middleware(append_slash=True, merge_slashes=True)
    # Only add the middleware once
    if norm not in app.middlewares:
        app.middlewares.append(norm)

    async def _index(request: web.Request) -> web.StreamResponse:
        index_path = os.path.join(ui_dir, "index.html")
        if not os.path.exists(index_path):
            return web.Response(status=500, text=f"index.html not found in {ui_dir}")
        return web.FileResponse(index_path)

    # Serve index for "/" and "/ui/"
    app.router.add_get("/", _index)
    app.router.add_get("/ui/", _index)

    # Serve static assets from ui_dir mounted at /ui (e.g., /ui/logo.png)
    # NOTE: In your index.html, keep asset links RELATIVE (e.g., "logo.png", "./main.js")
    # Do NOT use absolute paths like "/logo.png" under HA Ingress.
    app.router.add_static("/ui", ui_dir, show_index=False)
