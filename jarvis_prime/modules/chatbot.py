#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean Q&A, no riff banners, no persona)
# - Uses llm_client.py for model loading and generation
# - Reads chat_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed

import os
import json
import time
import asyncio
from typing import Dict, Any

import llm_client as llm

OPTIONS_PATH = "/data/options.json"
DEFAULTS = {
    "chat_enabled": True,
    "chat_history_turns": 3,
    "chat_history_turns_max": 5,
    "chat_max_total_tokens": 1200,
    "chat_reply_max_new_tokens": 256,
    "chat_system_prompt": "You are Jarvis. Answer clearly and factually.",
}

# ============================
# Helpers
# ============================

def _read_options() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _opt(key: str):
    opts = _read_options()
    return opts.get(key, DEFAULTS.get(key))

# ============================
# Prompt builder (no persona)
# ============================

def _prompt_for_chat(history, user_msg, sys_prompt: str) -> str:
    """
    Builds a plain assistant prompt with short history (no persona/riff).
    Phi-family uses <|system|>, others use [INST].
    """
    if not sys_prompt:
        sys_prompt = DEFAULTS["chat_system_prompt"]

    # Build history
    history_lines = []
    for role, text in history:
        if llm._is_phi3_family():
            if role == "user":
                history_lines.append(f"<|user|>\n{text}\n<|end|>")
            else:
                history_lines.append(f"<|assistant|>\n{text}\n<|end|>")
        else:
            history_lines.append(f"{role.upper()}: {text}")

    if llm._is_phi3_family():
        return (
            f"<|system|>\n{sys_prompt}\n<|end|>\n"
            + "\n".join(history_lines)
            + f"\n<|user|>\n{user_msg}\n<|end|>\n<|assistant|>\n"
        )
    else:
        return (
            f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n"
            + "\n".join(history_lines)
            + f"\n{user_msg} [/INST]"
        )

# ============================
# Core entry point
# ============================

async def handle_message(source: str, text: str) -> str:
    if not _opt("chat_enabled"):
        return ""

    # Ensure model loaded (delegates to llm_client, uses options.json)
    ok = llm.ensure_loaded()
    if not ok:
        return "(chatbot) model not loaded"

    sys_prompt = str(_opt("chat_system_prompt") or DEFAULTS["chat_system_prompt"])
    history_turns = min(int(_opt("chat_history_turns") or 3), int(_opt("chat_history_turns_max") or 5))
    reply_max_new_tokens = int(_opt("chat_reply_max_new_tokens") or 256)
    max_total_tokens = int(_opt("chat_max_total_tokens") or 1200)

    # Maintain in-memory rolling history
    if not hasattr(handle_message, "_history"):
        handle_message._history = []  # [(role, text), ...]

    history = handle_message._history[-history_turns:]

    # Build prompt
    prompt = _prompt_for_chat(history, text, sys_prompt)

    # Token count + overflow guard
    try:
        n_in = len(llm.LLM.tokenize(prompt.encode("utf-8"), add_bos=True))
    except Exception:
        n_in = len(prompt) // 4

    if llm._would_overflow(n_in, reply_max_new_tokens, llm.DEFAULT_CTX, reserve=256):
        return "(chatbot) prompt too long"

    # Generate reply
    out = llm._do_generate(
        prompt,
        timeout=20,
        base_url="",
        model_url="",
        model_name_hint="",
        max_tokens=reply_max_new_tokens,
        with_grammar_auto=False
    )
    reply = out.strip() if out else "(no reply)"

    # Update history
    history.append(("user", text))
    history.append(("assistant", reply))
    handle_message._history = history[-history_turns:]

    return reply

# ============================
# Optional HTTP API
# ============================

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    import uvicorn

    app = FastAPI()

    @app.post("/chat")
    async def chat_ep(body: Dict[str, Any]):
        msg = body.get("text", "")
        out = await handle_message("http", msg)
        return JSONResponse({"reply": out})

    if __name__ == "__main__":
        uvicorn.run(app, host="0.0.0.0", port=8099)

except ImportError:
    if __name__ == "__main__":
        print("FastAPI not installed; chatbot HTTP API disabled")