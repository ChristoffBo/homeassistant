#!/usr/bin/env python3
# /app/websocket.py

import os, json, asyncio, aiohttp, websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

# ======================================================
# Load HA options.json directly
# ======================================================
CONFIG_FILE = "/data/options.json"
cfg = {}
try:
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
except Exception:
    pass

ENABLED = str(cfg.get("intake_ws_enabled", False)).lower() in ("1", "true", "yes")
INTAKE_PORT = int(cfg.get("intake_ws_port", os.environ.get("WS_PORT", 8765)))
AUTH_TOKEN = cfg.get("intake_ws_token", os.environ.get("WS_TOKEN", "changeme"))
INTERNAL_EMIT = os.environ.get("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

# ======================================================
# Forward into Jarvis
# ======================================================
async def process_intake(data: dict):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(INTERNAL_EMIT, json=data) as resp:
                if resp.status != 200:
                    print(f"[WS] Forward failed {resp.status}")
                else:
                    print("[WS] Forwarded:", data)
    except Exception as e:
        print("[WS] Error forwarding:", e)

# ======================================================
# Handler
# ======================================================
connected = set()

async def handler(ws, path):
    # Parse ?token
    token = None
    try:
        if "?" in path:
            q = dict(p.split("=", 1) for p in path.split("?", 1)[1].split("&"))
            token = q.get("token")
    except:
        pass
    if token != AUTH_TOKEN:
        await ws.send(json.dumps({"status": "error", "error": "Auth failed"}))
        await ws.close()
        return

    connected.add(ws)
    print(f"[WS] Client connected ({len(connected)})")

    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
                await process_intake(data)
                await ws.send(json.dumps({"status": "ok"}))
            except Exception as e:
                await ws.send(json.dumps({"status": "error", "error": str(e)}))
    except (ConnectionClosedError, ConnectionClosedOK):
        pass
    finally:
        connected.remove(ws)
        print(f"[WS] Client disconnected ({len(connected)})")

# ======================================================
# Main
# ======================================================
async def main():
    if not ENABLED:
        print("[WS] Intake disabled by config")
        await asyncio.Future()
        return

    async with websockets.serve(handler, "0.0.0.0", INTAKE_PORT):
        print(f"[WS] Intake running on :{INTAKE_PORT} (token={AUTH_TOKEN})")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())