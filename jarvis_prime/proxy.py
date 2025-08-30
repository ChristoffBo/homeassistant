# proxy.py — Message proxy writing to inbox + forwarding (FULL)
from __future__ import annotations
import os, json, traceback
from aiohttp import web, ClientSession
from beautify import beautify_message

try:
    from storage import save_message
except Exception:
    save_message = None

CONFIG_PATH = "/data/options.json"

def _load_cfg() -> dict:
    try:
        import json
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

async def _forward_gotify(cfg: dict, title: str, message: str, priority: int, extras: dict) -> dict:
    url = (cfg.get("proxy_gotify_url") or cfg.get("gotify_url") or "").rstrip("/")
    token = cfg.get("gotify_app_token") or cfg.get("gotify_client_token") or ""
    if not url or not token:
        return {"ok": False, "reason": "gotify disabled (missing url/token)"}
    api = f"{url}/message?token={token}"
    async with ClientSession() as s:
        async with s.post(api, json={"title": title, "message": message, "priority": int(priority), "extras": extras or {}}) as r:
            return {"ok": r.status < 300, "status": r.status}

async def handle_notify(request: web.Request) -> web.Response:
    cfg = _load_cfg()
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = (data.get("title") or "Untitled")[:200]
    body = data.get("body") or data.get("message") or ""
    source = data.get("source") or "proxy"
    priority = int(data.get("priority") or 5)
    extras = data.get("extras") or {}

    if cfg.get("beautify_enabled", True) and body:
        try: body = beautify_message(body)
        except Exception: pass

    msg_id = None
    if save_message:
        try:
            msg_id = save_message(title=title, body=body, source=source, priority=priority, extras=extras, inbound=1)
        except Exception:
            traceback.print_exc()

    forward = {}
    if cfg.get("push_gotify_enabled", True):
        forward["gotify"] = await _forward_gotify(cfg, title, body, priority, extras)

    return web.json_response({"ok": True, "id": msg_id, "forward": forward})

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "mood": os.getenv("CHAT_MOOD","serious")})

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/notify", handle_notify)
    app.router.add_post("/message", handle_notify)
    app.router.add_get("/health", handle_health)
    return app

def run():
    cfg = _load_cfg()
    host = os.getenv("proxy_bind", cfg.get("proxy_bind","0.0.0.0"))
    port = int(os.getenv("proxy_port", str(cfg.get("proxy_port",2580))))
    print("[proxy] beautify loaded")
    print(f"[proxy] llm_client loaded (enabled={cfg.get('llm_enabled', False)})")
    print(f"[proxy] listening on {host}:{port} (LLM_ENABLED={str(cfg.get('llm_enabled', False)).upper()}, mood={os.getenv('CHAT_MOOD','serious')})")
    web.run_app(create_app(), host=host, port=port)

if __name__ == "__main__":
    run()
