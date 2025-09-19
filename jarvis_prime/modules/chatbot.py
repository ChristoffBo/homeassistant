#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime — ultra-minimal chat lane (sync, no persona, no banners)
# - Uses llm_client.ensure_loaded() + _do_generate(...)
# - Reads chatbot_* from /data/options.json
# - Exposes handle_message(source, text) -> str
# - Short rolling history per source

import json
import os
from collections import deque
from typing import Dict, Deque, List, Any

import llm_client  # your existing client

OPTIONS_PATH = "/data/options.json"

# -------- options ----------
def _opts() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _get(opts: Dict[str, Any], key: str, default):
    return opts.get(key, default)

# -------- history ----------
_HISTORY: Dict[str, Deque[Dict[str, str]]] = {}

def _hist_for(source: str, max_turns: int) -> Deque[Dict[str, str]]:
    dq = _HISTORY.get(source)
    if dq is None or dq.maxlen != max_turns:
        dq = deque(maxlen=max_turns)
        _HISTORY[source] = dq
    return dq

# -------- prompt build -----
def _build_prompt(system_prompt: str, history: List[Dict[str, str]], user_msg: str) -> str:
    # Use Phi3-style if available, else Llama INST
    if llm_client._is_phi3_family():
        parts = []
        if system_prompt:
            parts.append(f"<|system|>\n{system_prompt}\n<|end|>")
        for t in history:
            parts.append(f"<|user|>\n{t['user']}\n<|end|>")
            parts.append(f"<|assistant|>\n{t['bot']}\n<|end|>")
        parts.append(f"<|user|>\n{user_msg}\n<|end|>\n<|assistant|>")
        return "\n".join(parts)

    # Llama [INST] fallback
    sys = f"<<SYS>>{system_prompt}<</SYS>>" if system_prompt else ""
    conv = []
    for t in history:
        conv.append(f"[INST] {t['user']} [/INST] {t['bot']}")
    conv.append(f"[INST] {user_msg} [/INST]")
    return f"<s>{sys}\n" + "\n".join(conv)

# -------- public API --------
def handle_message(source: str, text: str) -> str:
    """
    Synchronous entrypoint used by bot.py.
    Always ensures the model is loaded. Never returns empty.
    """
    src = (source or "default").strip() or "default"
    user_msg = (text or "").strip()
    if not user_msg:
        return ""

    opts = _opts()

    # Allow either key (some configs used chat_enabled earlier)
    chatbot_enabled = bool(
        opts.get("chatbot_enabled", opts.get("chat_enabled", True))
    )
    if not chatbot_enabled:
        return ""

    max_turns = int(opts.get("chatbot_history_turns", 3) or 3)
    max_turns = max(1, min(max_turns, int(opts.get("chatbot_history_turns_max", 5) or 5)))
    reply_tokens = int(opts.get("chatbot_reply_max_new_tokens", 256) or 256)

    system_prompt = (
        opts.get("chatbot_system_prompt")
        or "You are Jarvis Prime, a concise, helpful assistant. No persona riffs, no emoji banners."
    )

    # Ensure model is ready (cheap if already loaded)
    loaded = llm_client.ensure_loaded()
    if not loaded:
        return "(error) LLM not loaded — check model path/permissions/options.json"

    hist = _hist_for(src, max_turns=max_turns)
    prompt = _build_prompt(system_prompt, list(hist), user_msg)

    # Basic console logging to see what’s happening
    try:
        print(f"[chatbot] src={src} hist={len(hist)} reply_tokens={reply_tokens}", flush=True)
        out = llm_client._do_generate(
            prompt,
            timeout=20,
            base_url="",
            model_url="",
            model_name_hint="",
            max_tokens=reply_tokens,
            with_grammar_auto=False,
        )
    except Exception as e:
        out = f"(error) {e}"

    reply = (out or "").strip()
    if not reply:
        reply = f"(fallback) I received: {user_msg[:140]}"

    hist.append({"user": user_msg, "bot": reply})
    return reply

# -------- quick local test ----
if __name__ == "__main__":
    print("Chatbot self-test. Type Ctrl+C to quit.")
    try:
        while True:
            q = input("You: ").strip()
            if not q:
                continue
            a = handle_message("console", q)
            print("Bot:", a)
    except KeyboardInterrupt:
        pass