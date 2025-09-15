#!/usr/bin/env python3
"""
ha_notify.py — forward Jarvis Prime messages into Home Assistant's notify service.

- Reuses /data/options.json values:
    * ha_token                (already used by Jarvis for HA)
    * ha_url                  (optional; default uses Supervisor proxy)
    * push_ha_service         (your configured notify.* service)
- The caller (api_messages.py) maps push_ha_service -> ha_notify_service just-in-time.
"""

import aiohttp
import asyncio

DEFAULT_SUPERVISOR_PROXY = "http://supervisor/core/api"

async def _async_push(title: str, body: str, options: dict):
    ha_url = options.get("ha_url", DEFAULT_SUPERVISOR_PROXY)
    ha_token = options.get("ha_token")
    ha_service = options.get("ha_notify_service")  # provided by caller

    if not ha_token or not ha_service:
        print("[ha_notify] Missing ha_token or ha_notify_service in options.json")
        return

    # Accept both forms: "notify.mobile_app_xxx" and "notify/mobile_app_xxx"
    service_path = ha_service.replace(".", "/")
    if "/api/" not in ha_url:
        # Normal HA base (http://homeassistant:8123) -> add /api/services/...
        url = f"{ha_url.rstrip('/')}/api/services/{service_path}"
    else:
        # Supervisor proxy already includes /api
        url = f"{ha_url.rstrip('/')}/services/{service_path}"

    payload = {"title": title, "message": body}
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=10) as r:
                if r.status != 200:
                    text = await r.text()
                    print(f"[ha_notify] Failed {r.status}: {text}")
                else:
                    print(f"[ha_notify] Sent to {ha_service}: {title}")
    except Exception as e:
        print(f"[ha_notify] Exception: {e}")

def push_to_ha_notify(title: str, body: str, options: dict):
    """Public entry — safe to call from sync code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_async_push(title, body, options))
        else:
            loop.run_until_complete(_async_push(title, body, options))
    except RuntimeError:
        asyncio.run(_async_push(title, body, options))