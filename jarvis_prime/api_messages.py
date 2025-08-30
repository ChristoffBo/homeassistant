#!/usr/bin/env python3
"""
Jarvis Prime Inbox API & Stream Mirrors
- REST API: /api/messages, /api/inbox/settings
- UI:       /ui/ (serves index.html from same dir)
- Ingest mirrors:
    * Gotify stream (client token) -> save to DB
    * ntfy SSE (topic)             -> save to DB
- Fan-out on save:
    * Gotify push (app token)
    * ntfy publish
    * SMTP email (Gmail/relay)
- Auto-purge scheduler: daily checks applying off/daily/weekly/monthly
"""
from __future__ import annotations
import os, json, asyncio, aiohttp, aiohttp.web, traceback, time
from pathlib import Path
from typing import Dict, Any, Optional

import storage
import ntfy_client
import smtp_client

# --------------------
# Config from env
# --------------------
GOTIFY_ENABLED   = (os.getenv("INGEST_GOTIFY_ENABLED","true").lower() in ("1","true","yes"))
NTFY_ENABLED     = (os.getenv("INGEST_NTFY_ENABLED","false").lower() in ("1","true","yes"))
SMTP_INGEST_ON   = (os.getenv("INGEST_SMTP_ENABLED","true").lower() in ("1","true","yes"))  # informational

GOTIFY_URL       = (os.getenv("GOTIFY_URL","") or "").rstrip("/")
GOTIFY_CLIENT_TK = os.getenv("GOTIFY_CLIENT_TOKEN","")
GOTIFY_APP_TK    = os.getenv("GOTIFY_APP_TOKEN","")

NTFY_URL         = (os.getenv("NTFY_URL","") or "").rstrip("/")
NTFY_TOPIC       = os.getenv("NTFY_TOPIC","jarvis")

PUSH_GOTIFY_ON   = (os.getenv("PUSH_GOTIFY_ENABLED","true").lower() in ("1","true","yes"))
PUSH_NTFY_ON     = (os.getenv("PUSH_NTFY_ENABLED","false").lower() in ("1","true","yes"))
PUSH_SMTP_ON     = (os.getenv("PUSH_SMTP_ENABLED","false").lower() in ("1","true","yes"))

RETENTION_DAYS   = int(os.getenv("RETENTION_DAYS","30") or "30")
AUTOPURGE        = (os.getenv("AUTO_PURGE_POLICY","off") or "off").lower()  # off|daily|weekly|monthly

# HTTP Session
_session: aiohttp.ClientSession

# --------------------
# Helpers
# --------------------
def _delivered_meta() -> Dict[str, Any]:
    return {}

async def _fanout_deliver(source: str, title: str, body: str) -> Dict[str, Any]:
    delivered: Dict[str, Any] = {}
    # Gotify push (skip loopback)
    if PUSH_GOTIFY_ON and GOTIFY_URL and GOTIFY_APP_TK and source != "gotify":
        try:
            url = f"{GOTIFY_URL}/message?token={GOTIFY_APP_TK}"
            async with _session.post(url, data={"title": title, "message": body, "priority": "5"}, timeout=8) as r:
                delivered["gotify"] = {"status": r.status, "http": r.status}
        except Exception as e:
            delivered["gotify"] = {"error": str(e)}
    # ntfy push (skip loopback)
    if PUSH_NTFY_ON and NTFY_URL and NTFY_TOPIC and source != "ntfy":
        try:
            # Use local client to reuse credentials/env
            res = ntfy_client.publish(title, body, topic=NTFY_TOPIC)
            delivered["ntfy"] = res
        except Exception as e:
            delivered["ntfy"] = {"error": str(e)}
    # SMTP push
    if PUSH_SMTP_ON:
        try:
            res = smtp_client.send_mail(subject=title, body=body)
            delivered["smtp"] = res
        except Exception as e:
            delivered["smtp"] = {"error": str(e)}
    return delivered

# --------------------
# Stream mirrors
# --------------------
async def mirror_gotify(app: aiohttp.web.Application):
    if not (GOTIFY_ENABLED and GOTIFY_URL and GOTIFY_CLIENT_TK):
        return
    url = f"{GOTIFY_URL}/stream?token={GOTIFY_CLIENT_TK}"
    while True:
        try:
            async with _session.get(url, timeout=None) as r:
                async for line in r.content:
                    try:
                        text = line.decode("utf-8", "ignore").strip()
                        if not text or text.startswith(":"):  # SSE keepalive
                            continue
                        if text.startswith("data:"):
                            payload = json.loads(text[5:].strip())
                            title = payload.get("title") or "(gotify)"
                            message = payload.get("message") or ""
                            mid = storage.save_message("gotify", title, message, meta={"raw": payload})
                            # fan-out
                            delivered = await _fanout_deliver("gotify", title, message)
                            if delivered:
                                # backfill delivered to record
                                # simple update by re-saving a meta record (not critical if missed)
                                pass
                    except Exception:
                        continue
        except Exception:
            await asyncio.sleep(2.0)

async def mirror_ntfy(app: aiohttp.web.Application):
    if not (NTFY_ENABLED and NTFY_URL and NTFY_TOPIC):
        return
    # ntfy SSE endpoint: /<topic>/sse
    url = f"{NTFY_URL}/{NTFY_TOPIC}/sse"
    while True:
        try:
            async with _session.get(url, timeout=None) as r:
                async for line in r.content:
                    try:
                        text = line.decode("utf-8","ignore").strip()
                        if not text or text.startswith(":"):
                            continue
                        if text.startswith("data:"):
                            payload = json.loads(text[5:].strip())
                            event = payload.get("event")
                            if event not in ("message","open"):  # only persist real messages
                                continue
                            title = payload.get("title") or "(ntfy)"
                            message = payload.get("message") or payload.get("body") or ""
                            storage.save_message("ntfy", title, message, meta={"raw": payload})
                            delivered = await _fanout_deliver("ntfy", title, message)
                    except Exception:
                        continue
        except Exception:
            await asyncio.sleep(2.0)

# --------------------
# Auto purge
# --------------------
async def scheduler_autopurge(app: aiohttp.web.Application):
    while True:
        try:
            policy = (storage.get_setting("auto_purge_policy", AUTOPURGE) or "off").lower()
            days = int(storage.get_setting("retention_days", RETENTION_DAYS) or RETENTION_DAYS)
            if policy != "off":
                # run once per day
                storage.purge_older_than(days)
            await asyncio.sleep(86400)
        except Exception:
            await asyncio.sleep(3600)

# --------------------
# REST API
# --------------------
async def handle_list(request: aiohttp.web.Request):
    q = request.query.get("q") or None
    limit = int(request.query.get("limit","50"))
    items = storage.search_messages(q, limit)
    return aiohttp.web.json_response({"items": items})

async def handle_get(request: aiohttp.web.Request):
    mid = int(request.match_info["id"])
    rec = storage.get_message(mid)
    if not rec: raise aiohttp.web.HTTPNotFound()
    return aiohttp.web.json_response(rec)

async def handle_delete(request: aiohttp.web.Request):
    mid = int(request.match_info["id"])
    ok = storage.delete_message(mid)
    return aiohttp.web.json_response({"deleted": ok})

async def handle_save(request: aiohttp.web.Request):
    """Accepts POST JSON: {source,title,body,meta} and persists; triggers fan-out."""
    try:
        j = await request.json()
    except Exception:
        j = {}
    source = (j.get("source") or "api").lower()
    title  = j.get("title") or "(no title)"
    body   = j.get("body") or ""
    meta   = j.get("meta") or {}
    mid = storage.save_message(source, title, body, meta=meta)
    delivered = await _fanout_deliver(source, title, body)
    return aiohttp.web.json_response({"id": mid, "delivered": delivered})

async def handle_purge(request: aiohttp.web.Request):
    try:
        j = await request.json()
    except Exception:
        j = {}
    days = int(j.get("days") or storage.get_setting("retention_days", RETENTION_DAYS) or RETENTION_DAYS)
    removed = storage.purge_older_than(days)
    return aiohttp.web.json_response({"purged": removed})

async def handle_get_settings(request: aiohttp.web.Request):
    out = {
        "retention_days": storage.get_setting("retention_days", RETENTION_DAYS),
        "auto_purge": storage.get_setting("auto_purge_policy", AUTOPURGE),
    }
    return aiohttp.web.json_response(out)

async def handle_put_settings(request: aiohttp.web.Request):
    try:
        j = await request.json()
    except Exception:
        j = {}
    if "retention_days" in j:
        storage.set_setting("retention_days", int(j["retention_days"]))
    if "auto_purge" in j:
        storage.set_setting("auto_purge_policy", str(j["auto_purge"]).lower())
    return aiohttp.web.json_response({"ok": True})

# --------------------
# Static UI
# --------------------
def _ui_path() -> Path:
    # Serve index.html from same directory
    return Path(__file__).with_name("index.html")

async def handle_ui(request: aiohttp.web.Request):
    p = _ui_path()
    if not p.exists():
        raise aiohttp.web.HTTPNotFound()
    return aiohttp.web.FileResponse(path=str(p))

# --------------------
# App factory
# --------------------
async def on_startup(app: aiohttp.web.Application):
    storage.init_db()
    app["bg_tasks"] = []
    if GOTIFY_ENABLED and GOTIFY_URL and GOTIFY_CLIENT_TK:
        app["bg_tasks"].append(asyncio.create_task(mirror_gotify(app)))
    if NTFY_ENABLED and NTFY_URL and NTFY_TOPIC:
        app["bg_tasks"].append(asyncio.create_task(mirror_ntfy(app)))
    app["bg_tasks"].append(asyncio.create_task(scheduler_autopurge(app)))

async def on_cleanup(app: aiohttp.web.Application):
    for t in app.get("bg_tasks", []):
        t.cancel()

def make_app() -> aiohttp.web.Application:
    global _session
    _session = aiohttp.ClientSession()
    app = aiohttp.web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    # REST
    app.router.add_get("/api/messages", handle_list)
    app.router.add_get("/api/messages/{id:\d+}", handle_get)
    app.router.add_delete("/api/messages/{id:\d+}", handle_delete)
    app.router.add_post("/api/messages", handle_save)
    app.router.add_post("/api/messages/purge", handle_purge)
    app.router.add_get("/api/inbox/settings", handle_get_settings)
    app.router.add_put("/api/inbox/settings", handle_put_settings)
    # UI
    app.router.add_get("/ui/", handle_ui)
    app.router.add_get("/", handle_ui)
    return app

def main():
    app = make_app()
    port = int(os.getenv("INBOX_PORT","2581"))
    aiohttp.web.run_app(app, host="0.0.0.0", port=port, handle_signals=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
