#!/usr/bin/env python3
# /app/webhook_server.py
from __future__ import annotations

import os
import json
import traceback
from typing import Any, Dict, Optional, Tuple
from datetime import datetime

# Web server
try:
    from aiohttp import web
except Exception as e:
    raise SystemExit(f"[webhook] ❌ aiohttp not available: {e}")

# HTTP client for forwarding to Jarvis core
import requests

# ---------------------------
# Config helpers
# ---------------------------
def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# Env & options
BOT_NAME      = os.getenv("BOT_NAME", "Jarvis Prime")
WEBHOOK_BIND  = os.getenv("webhook_bind", os.getenv("WEBHOOK_BIND", "0.0.0.0"))
WEBHOOK_PORT  = int(os.getenv("webhook_port", os.getenv("WEBHOOK_PORT", "2590")))
WEBHOOK_TOKEN = os.getenv("webhook_token", os.getenv("WEBHOOK_TOKEN", ""))  # optional

# Forward to Jarvis core (bot.py)
INTERNAL_EMIT_URL = os.getenv("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

# Merge /data/options.json (and /data/config.json)
try:
    options = _load_json("/data/options.json")
    fallback = _load_json("/data/config.json")
    merged = {**fallback, **options}
    WEBHOOK_BIND = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass
    WEBHOOK_TOKEN = str(merged.get("webhook_token", WEBHOOK_TOKEN))
except Exception:
    merged = {}

print(f"[webhook] forwarding to {INTERNAL_EMIT_URL}")

# ---------------------------
# Utilities
# ---------------------------
def _safe_str(v: Any) -> str:
    try:
        if isinstance(v, (dict, list, tuple)):
            return json.dumps(v, ensure_ascii=False, separators=(",", ": "))
        return str(v)
    except Exception:
        try:
            return repr(v)
        except Exception:
            return ""

def _parse_priority(val: Any, default: int = 5) -> int:
    try:
        n = int(val)
        if n < 1: n = 1
        if n > 10: n = 10
        return n
    except Exception:
        return default

def _mk_source(headers: "web.BaseRequest.headers") -> Optional[str]:
    if "X-GitHub-Event" in headers:
        return "github"
    if "X-Health-Check" in headers:
        return "healthcheck"
    return None

def _require_token(req: "web.Request") -> bool:
    if not WEBHOOK_TOKEN:
        return True
    t = req.headers.get("X-Webhook-Token") or req.query.get("token") or ""
    return (t == WEBHOOK_TOKEN)

def _extract_payload(
    req_json: Optional[Dict[str, Any]],
    req_text: str,
    headers: "web.BaseRequest.headers"
) -> Tuple[str, str, int, Dict[str, Any]]:
    """
    Prefer JSON {title,message,priority,extras}, accept aliases and plain text.
    Special handling for *arr webhooks: Sonarr, Radarr, Lidarr, Readarr.
    """
    title, message, priority, extras = "", "", 5, {}

    if isinstance(req_json, dict):
        # *arr webhook handling
        if "eventType" in req_json:
            event = req_json.get("eventType", "Event")

            ua = headers.get("User-Agent", "").lower()
            app = "App"
            if "sonarr" in ua:
                app = "Sonarr"
            elif "radarr" in ua:
                app = "Radarr"
            elif "lidarr" in ua:
                app = "Lidarr"
            elif "readarr" in ua:
                app = "Readarr"

            # Try to extract title depending on app
            obj_title = ""
            if app == "Sonarr":
                obj_title = req_json.get("series", {}).get("title", "")
                eps = req_json.get("episodes", [])
                if eps and isinstance(eps, list):
                    ep = eps[0].get("title", "")
                    if ep:
                        message = f"Episode: {ep}"
            elif app == "Radarr":
                obj_title = req_json.get("movie", {}).get("title", "")
            elif app == "Lidarr":
                obj_title = req_json.get("artist", {}).get("artistName", "")
                track = req_json.get("track", {}).get("title", "")
                if track:
                    message = f"Track: {track}"
            elif app == "Readarr":
                obj_title = req_json.get("author", {}).get("authorName", "")
                book = req_json.get("book", {}).get("title", "")
                if book:
                    message = f"Book: {book}"

            if obj_title:
                title = f"{app} - {obj_title} ({event})"
            else:
                title = f"{app} - {event}"

            if not message:
                message = json.dumps(req_json, indent=2)

        else:
            # Generic JSON payload
            title   = _safe_str(req_json.get("title", "")) or _safe_str(req_json.get("subject", ""))
            message = (
                _safe_str(req_json.get("message", "")) or
                _safe_str(req_json.get("body", "")) or
                _safe_str(req_json.get("text", "")) or
                _safe_str(req_json.get("msg", "")) or
                ""
            )
            priority = _parse_priority(req_json.get("priority", req_json.get("prio", 5)))
            ex = req_json.get("extras", {})
            if isinstance(ex, dict):
                extras = ex
            else:
                try:
                    extras = dict(ex)  # type: ignore
                except Exception:
                    extras = {"raw_extras": _safe_str(ex)}
    else:
        message = (req_text or "").strip()

    if not title:
        title = "Notification"  # neutral fallback
        src = _mk_source(headers)
        if src:
            extras.setdefault("webhook::source", src)

    return title, message, priority, extras

def _emit_internal(
    title: str,
    body: str,
    priority: int = 5,
    source: str = "webhook",
    oid: str = ""
) -> Tuple[bool, int, str]:
    """
    Forward to Jarvis core so the central beautify/LLM/riffs pipeline runs.
    """
    try:
        r = requests.post(
            INTERNAL_EMIT_URL,
            json={
                "title": title or "Notification",
                "body": body or "",
                "priority": int(priority),
                "source": source,
                "id": oid
            },
            timeout=5
        )
        ok = r.ok
        return ok, r.status_code, ("" if ok else r.text[:300])
    except Exception as e:
        return False, 0, str(e)

# ---------------------------
# aiohttp Handlers
# ---------------------------
async def handle_root(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "jarvis-webhook", "bind": WEBHOOK_BIND, "port": WEBHOOK_PORT})

async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="OK", content_type="text/plain")

async def handle_webhook(request: web.Request) -> web.Response:
    if not _require_token(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    raw_text = ""
    req_json: Optional[Dict[str, Any]] = None

    # Try JSON first, fallback to text
    if request.can_read_body:
        try:
            req_json = await request.json()
        except Exception:
            try:
                raw_text = await request.text()
            except Exception:
                raw_text = ""

    title, message, priority, extras = _extract_payload(req_json, raw_text, request.headers)

    # Metadata (not yet forwarded, but available if needed)
    _ = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "subject": title,
        "provider": "Webhook",
        "path": request.rel_url.path,
        "method": request.method,
        "ip": request.headers.get("X-Forwarded-For") or request.remote or "",
        "user_agent": request.headers.get("User-Agent", "")
    }

    ok, status, info = _emit_internal(title, message, priority, "webhook", "")
    return web.json_response(
        {"ok": bool(ok), "status": status, "info": info},
        status=(200 if ok else 502)
    )

# ---------------------------
# App bootstrap
# ---------------------------
def _build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/healthz", handle_health)
    app.router.add_post("/webhook", handle_webhook)
    return app

def main() -> None:
    app = _build_app()
    print(f"[webhook] 🌐 Webhook server listening on {WEBHOOK_BIND}:{WEBHOOK_PORT}")
    if WEBHOOK_TOKEN:
        print("[webhook] 🔒 Shared token is ENABLED (via X-Webhook-Token or ?token=...)")
    else:
        print("[webhook] 🔓 No shared token set (accepting unauthenticated requests)")
    try:
        web.run_app(app, host=WEBHOOK_BIND, port=WEBHOOK_PORT, print=None)
    except KeyboardInterrupt:
        print("[webhook] stopping (KeyboardInterrupt)")
    except Exception:
        print("[webhook] ❌ server crashed:\n" + traceback.format_exc())

if __name__ == "__main__":
    main()