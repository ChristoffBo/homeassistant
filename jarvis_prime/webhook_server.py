#!/usr/bin/env python3
# /app/webhook_server.py
from __future__ import annotations

import os
import json
import asyncio
import traceback
from typing import Any, Dict, Optional, Tuple
from datetime import datetime  # ADDITIVE: for riff facts timestamp

# Web server
try:
    from aiohttp import web
except Exception as e:
    raise SystemExit(f"[webhook] ❌ aiohttp not available: {e}")

# HTTP client to forward to Gotify
try:
    import requests
except Exception as e:
    requests = None  # type: ignore
    print(f"[webhook] ⚠️ requests not available: {e}")

# ---------------------------
# Config helpers
# ---------------------------
def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# Defaults (env first, then /data/options.json can override below)
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
BOT_NAME     = os.getenv("BOT_NAME", "Jarvis Prime")
WEBHOOK_BIND = os.getenv("webhook_bind", os.getenv("WEBHOOK_BIND", "0.0.0.0"))
WEBHOOK_PORT = int(os.getenv("webhook_port", os.getenv("WEBHOOK_PORT", "2590")))
WEBHOOK_TOKEN = os.getenv("webhook_token", os.getenv("WEBHOOK_TOKEN", ""))  # optional

# Merge /data/options.json (and /data/config.json) if present
try:
    options = _load_json("/data/options.json")
    fallback = _load_json("/data/config.json")
    merged = {**fallback, **options}
    GOTIFY_URL   = str(merged.get("gotify_url", GOTIFY_URL)).rstrip("/")
    APP_TOKEN    = str(merged.get("gotify_app_token", APP_TOKEN))
    WEBHOOK_BIND = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass
    WEBHOOK_TOKEN = str(merged.get("webhook_token", WEBHOOK_TOKEN))
except Exception:
    merged = {}

if not GOTIFY_URL or not APP_TOKEN:
    print("[webhook] ⚠️ gotify_url / gotify_app_token not configured; forwarding will fail.")

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

def _mk_title_source(headers: "web.BaseRequest.headers") -> Tuple[str, Optional[str]]:
    """
    Quick heuristics to craft a title and source based on common webhook headers.
    """
    # GitHub
    if "X-GitHub-Event" in headers:
        return (f"[GitHub] {headers.get('X-GitHub-Event')}", "github")
    # Uptime/health-like
    if "X-Health-Check" in headers:
        return ("[HealthCheck] Event", "healthcheck")
    # Generic
    return ("Webhook Event", None)

def _require_token(req: "web.Request") -> bool:
    if not WEBHOOK_TOKEN:
        return True
    t = req.headers.get("X-Webhook-Token") or req.query.get("token") or ""
    return (t == WEBHOOK_TOKEN)

def _extract_payload(req_json: Optional[Dict[str, Any]], req_text: str, headers: "web.BaseRequest.headers") -> Tuple[str, str, int, Dict[str, Any]]:
    """
    Flexible extraction:
      - Prefer JSON fields: title, message, priority, extras
      - Accept alternate keys: subject, body, text, msg
      - Fallback: raw body as message
    """
    title, message, priority, extras = "", "", 5, {}

    if isinstance(req_json, dict):
        # Primary keys
        title   = _safe_str(req_json.get("title", "")) or _safe_str(req_json.get("subject", ""))
        message = _safe_str(req_json.get("message", "")) or _safe_str(req_json.get("body", "")) or _safe_str(req_json.get("text", "")) or _safe_str(req_json.get("msg", ""))
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
        # Non-JSON; treat entire body as message
        message = (req_text or "").strip()

    if not title:
        t_guess, src = _mk_title_source(headers)
        title = t_guess
        if src:
            extras.setdefault("webhook::source", src)

    return title, message, priority, extras

def _post_gotify(title: str, message: str, priority: int = 5, extras: Optional[Dict[str, Any]] = None) -> Tuple[bool, int, str]:
    if not requests:
        return False, 0, "requests not installed"
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}".rstrip("/")
    payload: Dict[str, Any] = {
        "title": title,                # IMPORTANT: do NOT prefix with "🧠 Jarvis Prime: ..."
        "message": message or "",
        "priority": int(priority),
    }
    if extras:
        payload["extras"] = extras
    try:
        r = requests.post(url, json=payload, timeout=8)
        ok = r.ok
        status = r.status_code
        if not ok:
            return False, status, f"HTTP {status}: {r.text[:300]}"
        return True, status, "OK"
    except Exception as e:
        return False, 0, f"{e}"

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

    # Try JSON first
    if request.can_read_body:
        try:
            req_json = await request.json()
        except Exception:
            # Fallback to text
            try:
                raw_text = await request.text()
            except Exception:
                raw_text = ""

    title, message, priority, extras = _extract_payload(req_json, raw_text, request.headers)

    # ---------- ADDITIVE: attach riff hint + facts so Beautify can riff ----------
    try:
        client_ip = request.headers.get("X-Forwarded-For") or request.remote or ""
    except Exception:
        client_ip = ""
    facts = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "subject": title,
        "provider": "Webhook",
        "path": request.rel_url.path,
        "method": request.method,
        "ip": client_ip,
        "user_agent": request.headers.get("User-Agent", "")
    }
    riff_pack = {"riff_hint": True, "source": "webhook", "facts": facts}
    if isinstance(extras, dict):
        # keep caller extras but ensure riff fields are present
        merged_extras = dict(extras)
        # don't let caller override the hint/facts accidentally
        merged_extras.setdefault("riff_hint", True)
        merged_extras.setdefault("source", "webhook")
        merged_extras.setdefault("facts", facts)
    else:
        merged_extras = riff_pack
    # ---------------------------------------------------------------------------

    # Minor safety: avoid accidentally tagging as our own repost
    # (bot.py skips messages whose title starts with "🧠 Jarvis Prime: ...")
    # We deliberately do NOT add that prefix here.

    ok, status, info = _post_gotify(title, message, priority, merged_extras)
    result = {"ok": bool(ok), "status": status, "info": info}
    return web.json_response(result, status=(200 if ok else 502))

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
        print("[webhook] 🔒 Shared token is ENABLED (required via X-Webhook-Token or ?token=...)")
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