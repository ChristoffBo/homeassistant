# smtp_server.py — SMTP intake -> inbox + optional gotify (FULL)
from __future__ import annotations
import asyncio, json
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import AsyncMessage
from aiohttp import ClientSession

try:
    from storage import save_message, purge_older_than
except Exception:
    save_message = None
    def purge_older_than(*a, **k): return 0

CONFIG_PATH = "/data/options.json"

def _cfg() -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

async def _forward_gotify(title: str, message: str, priority: int, extras: dict) -> dict:
    cfg = _cfg()
    if not cfg.get("push_gotify_enabled", True):
        return {"ok": False, "reason": "push disabled"}
    url = (cfg.get("gotify_url") or "").rstrip("/")
    token = cfg.get("gotify_app_token") or cfg.get("gotify_client_token") or ""
    if not url or not token:
        return {"ok": False, "reason": "missing gotify url/token"}
    api = f"{url}/message?token={token}"
    async with ClientSession() as s:
        async with s.post(api, json={"title": title, "message": message, "priority": int(priority), "extras": extras or {}}) as r:
            return {"ok": r.status < 300, "status": r.status}

class Handler(AsyncMessage):
    async def handle_message(self, message):
        subj = message.get('Subject', 'No subject')
        # prefer text/plain
        body = ""
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
        else:
            body = message.get_payload(decode=True).decode(message.get_content_charset() or "utf-8", errors="replace")
        extras = {"smtp": {"from": message.get("From",""), "to": message.get("To","")}}
        # write to inbox
        if save_message:
            try: save_message(title=subj, body=body, source="smtp", priority=5, extras=extras, inbound=1)
            except Exception: pass
        # forward
        await _forward_gotify(subj, body, 5, extras)
        try: purge_older_than(None)
        except Exception: pass
        return '250 OK'

def run():
    cfg = _cfg()
    controller = Controller(Handler(), hostname=cfg.get("smtp_bind","0.0.0.0"), port=int(cfg.get("smtp_port",2525)), decode_data=False)
    controller.start()
    print(f"[smtp] listening on {cfg.get('smtp_bind','0.0.0.0')}:{int(cfg.get('smtp_port',2525))}")
    try:
        while True:
            asyncio.sleep(3600)
    except KeyboardInterrupt:
        controller.stop()

if __name__ == "__main__":
    run()
