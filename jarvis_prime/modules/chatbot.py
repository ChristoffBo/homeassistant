#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners, no persona)
# - Uses llm_client.py for generation
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) as sync for bot.py
# - Optional HTTP API if FastAPI is installed

import os
import json
import time
import asyncio
import re
from typing import Dict, Any, List
from collections import deque

import llm_client

# ----------------------------
# Config (reads chatbot_* keys)
# ----------------------------

OPTIONS_PATH = "/data/options.json"
DEFAULTS = {
    "chatbot_enabled": True,
    "chatbot_history_turns": 3,
    "chatbot_history_turns_max": 5,
    "chatbot_max_total_tokens": 1200,
    "chatbot_reply_max_new_tokens": 256,
    "chatbot_system_prompt": "You are Jarvis Prime, a helpful and knowledgeable assistant. "
                             "Answer clearly and concisely without persona riffs or extra banners."
}

def _read_options() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            opts = json.load(f)
            return opts
    except Exception:
        return {}

def _get_opt(opts: Dict[str, Any], key: str, default: Any) -> Any:
    return opts.get(key, DEFAULTS.get(key, default))

# ----------------------------
# Chat state
# ----------------------------

_HISTORY: Dict[str, deque] = {}

def _get_history(source: str, max_turns: int) -> deque:
    if source not in _HISTORY:
        _HISTORY[source] = deque(maxlen=max_turns)
    return _HISTORY[source]

# ----------------------------
# Prompt building
# ----------------------------

def _build_prompt(system_prompt: str, history: List[Dict[str, str]], user_msg: str) -> str:
    """
    Build chat-style prompt for Phi-family GGUF models.
    """
    parts = []
    if llm_client._is_phi3_family():
        if system_prompt:
            parts.append(f"<|system|>\n{system_prompt}\n<|end|>")
        for turn in history:
            parts.append(f"<|user|>\n{turn['user']}\n<|end|>")
            parts.append(f"<|assistant|>\n{turn['bot']}\n<|end|>")
        parts.append(f"<|user|>\n{user_msg}\n<|end|>\n<|assistant|>")
        return "\n".join(parts)
    else:
        sys = f"<<SYS>>{system_prompt}<</SYS>>" if system_prompt else ""
        conv = []
        for turn in history:
            conv.append(f"[INST] {turn['user']} [/INST] {turn['bot']}")
        conv.append(f"[INST] {user_msg} [/INST]")
        return f"<s>{sys}\n" + "\n".join(conv)

# ----------------------------
# Async core function
# ----------------------------

async def handle_message_async(source: str, text: str) -> str:
    opts = _read_options()
    if not _get_opt(opts, "chatbot_enabled", True):
        return ""

    history_turns = min(
        int(_get_opt(opts, "chatbot_history_turns", 3)),
        int(_get_opt(opts, "chatbot_history_turns_max", 5))
    )
    max_total_tokens = int(_get_opt(opts, "chatbot_max_total_tokens", 1200))
    reply_max_tokens = int(_get_opt(opts, "chatbot_reply_max_new_tokens", 256))
    system_prompt = _get_opt(opts, "chatbot_system_prompt", DEFAULTS["chatbot_system_prompt"])

    hist = _get_history(source, history_turns)
    prompt = _build_prompt(system_prompt, list(hist), text)

    try:
        out = llm_client._do_generate(
            prompt,
            timeout=20,
            base_url="",
            model_url="",
            model_path="",
            model_name_hint="",
            max_tokens=reply_max_tokens,
            with_grammar_auto=False
        )
    except Exception as e:
        out = f"(error: {e})"

    reply = (out or "").strip()
    if reply:
        hist.append({"user": text, "bot": reply})
    return reply

# ----------------------------
# Sync wrapper (alias for bot.py)
# ----------------------------

def handle_message(source: str, text: str) -> str:
    """
    Sync wrapper so bot.py can call handle_message(...) directly.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(handle_message_async(source, text))
        else:
            return loop.run_until_complete(handle_message_async(source, text))
    except RuntimeError:
        return asyncio.run(handle_message_async(source, text))

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
        out = await handle_message_async("http", msg)
        return JSONResponse({"reply": out})

    if __name__ == "__main__":
        uvicorn.run(app, host="0.0.0.0", port=8099)

except ImportError:
    if __name__ == "__main__":
        print("FastAPI not installed; chatbot HTTP API disabled")