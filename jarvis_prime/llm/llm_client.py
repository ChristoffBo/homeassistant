#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners)
# - Uses your existing llm_client.py (rewrite only, no persona riffing)
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed

import os
import sys
import json
import asyncio
import re
from typing import Dict, Optional

# ----------------------------
# Path + Imports
# ----------------------------
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import llm_client  # your working LLM module

# ----------------------------
# Config
# ----------------------------
OPTIONS_PATH = "/data/options.json"
DEFAULTS = {
    "chat_enabled": True,
    "chat_history_turns": 3,
    "chat_history_turns_max": 5,
    "chat_max_total_tokens": 1200,
    "chat_reply_max_new_tokens": 256,
    "chat_system_prompt": "You are Jarvis, a helpful assistant. Answer clearly and concisely.",
}

def _load_options() -> Dict:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception:
        return {}

def _get_opt(key: str, default):
    opts = _load_options()
    return opts.get(key, DEFAULTS.get(key, default))

# ----------------------------
# Core Chat
# ----------------------------
async def handle_message(source: str, text: str) -> str:
    if not _get_opt("chat_enabled", True):
        return ""

    system_prompt = _get_opt("chat_system_prompt", DEFAULTS["chat_system_prompt"])
    max_new_tokens = int(_get_opt("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
    timeout = 20  # seconds, safe default

    try:
        # Directly use llm_client.rewrite for chat answers
        reply = llm_client.rewrite(
            text=f"{system_prompt}\n\nUser: {text}\nAssistant:",
            mood="neutral",
            timeout=timeout,
            max_chars=0,
            max_lines=0,
        )
        return reply.strip()
    except Exception as e:
        return f"LLM error: {e}"

# ----------------------------
# Optional: FastAPI HTTP/WS API
# ----------------------------
try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    import uvicorn

    app = FastAPI()

    @app.post("/chat")
    async def chat_api(payload: Dict):
        text = payload.get("text", "")
        source = payload.get("source", "api")
        out = await handle_message(source, text)
        return JSONResponse({"reply": out})

    if __name__ == "__main__":
        uvicorn.run(app, host="0.0.0.0", port=8099)

except ImportError:
    # FastAPI not installed, run in library mode only
    pass