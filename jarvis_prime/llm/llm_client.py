#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners)
# - Uses your existing llm_client.py (rewrite/riff)
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed

import os
import json
import time
import asyncio
import re
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque, defaultdict

import llm_client  # ✅ fixed: import your llm_client with rewrite()

# ----------------------------
# Config (reads chatbot_* keys)
# ----------------------------

OPTIONS_PATH = "/data/options.json"
DEFAULTS = {
    "chat_enabled": True,                  # derived from chatbot_enabled
    "chat_history_turns": 3,               # from chatbot_history_turns
    "chat_history_turns_max": 5,
    "chat_max_total_tokens": 1200,         # from chatbot_max_total_tokens
    "chat_reply_max_new_tokens": 256,      # from chatbot_reply_max_new_tokens
    "chat_system_prompt": "You are Jarvis, a helpful assistant. Keep answers clear and concise.",
}

def _read_options() -> Dict[str, any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _opt(key: str):
    opts = _read_options()
    return opts.get(key, DEFAULTS.get(key))

# ----------------------------
# Chat History
# ----------------------------

class ChatHistory:
    def __init__(self, max_turns: int = 3):
        self.max_turns = max_turns
        self.history: Deque[Tuple[str, str]] = deque(maxlen=max_turns)

    def add(self, user: str, assistant: str):
        self.history.append((user, assistant))

    def build_prompt(self, system_prompt: str, new_user: str) -> str:
        parts = [f"System: {system_prompt}"]
        for u, a in self.history:
            parts.append(f"User: {u}")
            parts.append(f"Assistant: {a}")
        parts.append(f"User: {new_user}")
        return "\n".join(parts)

# ----------------------------
# LLM call wrapper
# ----------------------------

def call_llm_for_chat(prompt: str, max_new_tokens: int = 256, timeout: int = 20) -> str:
    try:
        reply = llm_client.rewrite(
            text=prompt,
            mood="neutral",
            timeout=timeout,
            max_chars=0,
            max_lines=0
        )
        return reply.strip() if reply else "(no reply)"
    except Exception as e:
        return f"[LLM error: {e}]"

# ----------------------------
# Chatbot Engine
# ----------------------------

class ChatBot:
    def __init__(self):
        self.enabled = bool(_opt("chatbot_enabled"))
        self.history_turns = int(_opt("chatbot_history_turns") or DEFAULTS["chat_history_turns"])
        self.max_total_tokens = int(_opt("chatbot_max_total_tokens") or DEFAULTS["chat_max_total_tokens"])
        self.reply_max_new_tokens = int(_opt("chatbot_reply_max_new_tokens") or DEFAULTS["chat_reply_max_new_tokens"])
        self.system_prompt = str(_opt("chatbot_system_prompt") or DEFAULTS["chat_system_prompt"])
        self.history = ChatHistory(self.history_turns)

    async def handle_message(self, source: str, text: str) -> str:
        if not self.enabled:
            return "(chat disabled)"
        prompt = self.history.build_prompt(self.system_prompt, text)
        reply = call_llm_for_chat(
            prompt,
            max_new_tokens=self.reply_max_new_tokens,
            timeout=20
        )
        self.history.add(text, reply)
        return reply

# ----------------------------
# Singleton
# ----------------------------

_bot: Optional[ChatBot] = None

def get_bot() -> ChatBot:
    global _bot
    if _bot is None:
        _bot = ChatBot()
    return _bot

# Public entrypoint for bot.py
async def handle_message(source: str, text: str) -> str:
    bot = get_bot()
    return await bot.handle_message(source, text)

# ----------------------------
# Optional HTTP/WS API (if FastAPI installed)
# ----------------------------
try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    import uvicorn

    app = FastAPI()

    @app.post("/chat")
    async def chat_api(payload: Dict[str, str]):
        msg = payload.get("message", "")
        reply = await handle_message("api", msg)
        return JSONResponse({"reply": reply})

    if __name__ == "__main__":
        uvicorn.run(app, host="0.0.0.0", port=8099)
except ImportError:
    if __name__ == "__main__":
        async def _demo():
            bot = get_bot()
            while True:
                txt = input("You: ")
                if not txt.strip():
                    break
                reply = await bot.handle_message("cli", txt)
                print("Jarvis:", reply)

        asyncio.run(_demo())