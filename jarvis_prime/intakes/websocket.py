#!/usr/bin/env python3
# /app/websocket.py
#
# Jarvis Prime — WebSocket Intake
# Provides a persistent intake channel: /intake/ws
#
# - Clients connect: ws://<host>:8765/intake/ws?token=<secret>
# - Messages are JSON: {"title": "Backup complete", "message": "Radarr finished"}
# - Each message is acked: {"status": "ok"}
# - Multiple clients supported concurrently

import os
import json
import asyncio
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

# ======================================================
# Config
# ======================================================
INTAKE_PORT = int(os.environ.get("WS_PORT", 8765))
AUTH_TOKEN = os.environ.get("WS_TOKEN", "changeme")  # set in options.json or env
INTERNAL_EMIT = os.environ.get("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

# ======================================================
# Forward into Jarvis
# ======================================================
async def process_intake(data: dict):
    """Forward intake payload into Jarvis via /internal/emit"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(INTERNAL_EMIT, json=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[WS] Forward failed: {resp.status} {text}")
                else:
                    print("[WS] Forwarded to Jarvis:", data)
    except Exception as e:
        print("[WS] Error forwarding:", e)

# ======================================================
# Connection manager
# ======================================================
connected_clients = set()

async def handler(ws, path):
    # --- auth ---
    try:
        query = dict(pair.split("=", 1) for pair in path.split("?")[1].split("&"))
    except Exception:
        query = {}

    token = query.get("token")
    if not token:
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=5)
            token = json.loads(first).get("token")
        except Exception:
            await ws.send(json.dumps({"status": "error", "error": "Missing token"}))
            await ws.close()
            return

    if token != AUTH_TOKEN:
        await ws.send(json.dumps({"status": "error", "error": "Auth failed"}))
        await ws.close()
        return

    # --- register client ---
    connected_clients.add(ws)
    print(f"[WS] Client connected ({len(connected_clients)} total)")

    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
                await process_intake(data)
                await ws.send(json.dumps({"status": "ok"}))
            except Exception as e:
                err = str(e)
                print("[WS] Error handling message:", err)
                await ws.send(json.dumps({"status": "error", "error": err}))
    except (ConnectionClosedError, ConnectionClosedOK):
        pass
    finally:
        connected_clients.remove(ws)
        print(f"[WS] Client disconnected ({len(connected_clients)} left)")

# ======================================================
# Main
# ======================================================
async def main():
    async with websockets.serve(handler, "0.0.0.0", INTAKE_PORT, ping_interval=20, ping_timeout=20):
        print(f"[WS] Intake WebSocket running on port {INTAKE_PORT}")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[WS] Shutting down")