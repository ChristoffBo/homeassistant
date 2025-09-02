#!/usr/bin/env python3
# /app/webhook_server.py

import asyncio
import json
import os
from aiohttp import web

import beautify
try:
    import llm
except ImportError:
    llm = None

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# =============================
# Webhook handler
# =============================

async def handle_hook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        try:
            data = await request.post()
            payload = dict(data)
        except Exception:
            return web.json_response({"error": "Invalid payload"}, status=400)

    title = payload.get("title") or "Webhook Event"
    body = payload.get("body") or json.dumps(payload, indent=2)

    # Run through LLM if enabled, otherwise beautifier
    text, extras = None, {}
    if llm and os.getenv("LLM_ENABLED", "false").lower() == "true":
        try:
            rewritten = llm.rewrite(body, mood="neutral")
            text, extras = beautify.beautify_message(title, rewritten, source_hint="webhook")
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ LLM rewrite failed in webhook: {e}", flush=True)
            text, extras = beautify.beautify_message(title, body, source_hint="webhook")
    else:
        text, extras = beautify.beautify_message(title, body, source_hint="webhook")

    print(f"[{BOT_NAME}] 📥 Webhook ingested: {title}", flush=True)

    return web.json_response({
        "ok": True,
        "title": title,
        "text": text,
        "extras": extras
    })


# =============================
# Server bootstrap
# =============================

async def run_webhook_server(host: str = "0.0.0.0", port: int = 2590):
    app = web.Application()
    app.router.add_post("/hook", handle_hook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"[{BOT_NAME}] 🌐 Webhook server listening on {host}:{port}", flush=True)

    # Keep running forever
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(run_webhook_server())