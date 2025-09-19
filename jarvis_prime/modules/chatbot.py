#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners)
# - Uses the same llm_client pipeline as riff/rewrite
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Keeps short conversation history (if enabled)
# - Optional HTTP API if FastAPI is installed

import os
import json
import asyncio
from typing import Dict, List, Any
from collections import deque

# ----------------------------
# Config loader
# ----------------------------

OPTIONS_PATH = "/data/options.json"
DEFAULTS = {
    "chatbot_enabled": True,
    "chatbot_history_turns": 3,
    "chatbot_max_total_tokens": 2048,
    "chatbot_reply_max_new_tokens": 256,
}

def load_options() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r") as f:
            cfg = json.load(f)
            return {**DEFAULTS, **cfg.get("options", {})}
    except Exception:
        return DEFAULTS.copy()

OPTIONS = load_options()

# ----------------------------
# History buffer
# ----------------------------

_history: Dict[str, deque] = {}

def get_history(src: str) -> deque:
    if src not in _history:
        _history[src] = deque(maxlen=OPTIONS["chatbot_history_turns"])
    return _history[src]

# ----------------------------
# Core LLM call
# ----------------------------

try:
    from llm_client import generate_reply
except ImportError:
    # Minimal fallback if llm_client missing
    def generate_reply(prompt: str, max_tokens: int = 128, timeout: int = 30) -> str:
        return f"(llm_client not found) {prompt[:100]}..."

def _build_prompt(history: deque, user_text: str) -> List[Dict[str, str]]:
    """Builds chat messages list for llama.cpp chat template."""
    msgs = []
    for role, content in history:
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs

def handle_message(source: str, text: str) -> str:
    """
    Sync entrypoint for bot.py.
    Calls llm_client.generate_reply with user + history.
    """
    if not OPTIONS.get("chatbot_enabled", True):
        return ""

    hist = get_history(source)
    msgs = _build_prompt(hist, text)

    # Serialize messages into a simple prompt
    prompt = ""
    for m in msgs:
        prompt += f"{m['role'].upper()}: {m['content']}\n"
    prompt += "ASSISTANT:"

    try:
        out = generate_reply(
            prompt,
            max_tokens=OPTIONS.get("chatbot_reply_max_new_tokens", 256),
            timeout=OPTIONS.get("llm_timeout_seconds", 60),
        )
    except Exception as e:
        return f"(chatbot error: {e})"

    # update history
    hist.append(("user", text))
    hist.append(("assistant", out.strip()))

    return out.strip()

# ----------------------------
# Optional HTTP API
# ----------------------------

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    import uvicorn

    app = FastAPI()

    @app.post("/chat")
    async def chat_ep(body: Dict[str, Any]):
        msg = body.get("text", "")
        out = handle_message("http", msg)
        return JSONResponse({"reply": out})

    if __name__ == "__main__":
        uvicorn.run(app, host="0.0.0.0", port=8099)

except ImportError:
    if __name__ == "__main__":
        print("FastAPI not installed; chatbot HTTP API disabled")