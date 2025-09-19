#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners)
# - Reads chatbot_* keys from /data/options.json
# - Manages chat history and prompt formatting
# - Delegates all llama.cpp runtime settings to llm_client.py
# - Exposes handle_message(source, text) for bot.py
# - Optional HTTP/WS API if FastAPI is installed

import os
import json
import time
import asyncio
import re
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque, defaultdict

# ----------------------------
# Config
# ----------------------------

OPTIONS_PATH = "/data/options.json"
DEFAULTS = {
    "chatbot_enabled": True,
    "chatbot_history_turns": 3,
    "chatbot_max_total_tokens": 1200,
    "chatbot_reply_max_new_tokens": 256,
    "chat_system_prompt": "You are Jarvis Prime, a concise homelab assistant.",
}

def _load_options() -> dict:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = {}

    out = DEFAULTS.copy()
    out["chatbot_enabled"] = bool(raw.get("chatbot_enabled", True))
    out["chatbot_history_turns"] = int(raw.get("chatbot_history_turns", 3))
    out["chatbot_max_total_tokens"] = int(raw.get("chatbot_max_total_tokens", 1200))
    out["chatbot_reply_max_new_tokens"] = int(raw.get("chatbot_reply_max_new_tokens", 256))
    if isinstance(raw.get("llm_system_prompt"), str) and raw.get("llm_system_prompt").strip():
        out["chat_system_prompt"] = raw["llm_system_prompt"].strip()
    return out

OPTS = _load_options()

# ----------------------------
# Token estimation
# ----------------------------

class _Tokenizer:
    def __init__(self):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._enc = None
    def count(self, text: str) -> int:
        if not text: return 0
        if self._enc:
            try: return len(self._enc.encode(text))
            except Exception: pass
        return max(1, (len(text) + 3) // 4)

TOKENIZER = _Tokenizer()

def tokens_of_messages(msgs: List[Tuple[str, str]]) -> int:
    total = 0
    for role, content in msgs:
        total += 4
        total += TOKENIZER.count(role) + TOKENIZER.count(content)
    total += 2
    return total

# ----------------------------
# Chat memory
# ----------------------------

class ChatMemory:
    def __init__(self, max_turns: int):
        self.max_turns = max_turns
        self.turns: Dict[str, Deque[Tuple[str, str]]] = defaultdict(lambda: deque(maxlen=self.max_turns))
        self.last_seen: Dict[str, float] = {}

    def append_turn(self, chat_id: str, user_msg: str, assistant_msg: str):
        dq = self.turns[chat_id]
        dq.append((user_msg, assistant_msg))
        self.last_seen[chat_id] = time.time()

    def get_context(self, chat_id: str) -> List[Tuple[str, str]]:
        return list(self.turns[chat_id])

    def set_max_turns(self, n: int):
        self.max_turns = n
        for cid, old in list(self.turns.items()):
            self.turns[cid] = deque(old, maxlen=self.max_turns)

    def GC(self, idle_seconds: int = 6 * 3600):
        now = time.time()
        drop = [cid for cid, ts in self.last_seen.items() if (now - ts) > idle_seconds]
        for cid in drop:
            self.turns.pop(cid, None)
            self.last_seen.pop(cid, None)

MEM = ChatMemory(OPTS["chatbot_history_turns"])

async def _bg_gc_loop():
    while True:
        await asyncio.sleep(1800)
        MEM.GC()

# ----------------------------
# LLM bridge
# ----------------------------

try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _is_ready() -> bool:
    return _LLM is not None

# ----------------------------
# Prompt building
# ----------------------------

def _build_prompt(msgs: List[Tuple[str, str]]) -> str:
    sys_chunks = [c for (r, c) in msgs if r == "system"]
    sys_text = "\n\n".join(sys_chunks).strip() if sys_chunks else DEFAULTS["chat_system_prompt"]

    if getattr(_LLM, "_is_phi3_family", None) and _LLM._is_phi3_family():
        buf: List[str] = []
        buf.append(f"<|system|>\n{sys_text}\n<|end|>")
        for r, c in msgs:
            if r == "user": buf.append(f"<|user|>\n{c}\n<|end|>")
            elif r == "assistant": buf.append(f"<|assistant|>\n{c}\n<|end|>")
        buf.append("<|assistant|>\n")
        return "\n".join(buf)

    convo: List[str] = []
    for r, c in msgs:
        if r == "user": convo.append(f"User: {c}")
        elif r == "assistant": convo.append(f"Assistant: {c}")
    convo.append("Assistant:")
    body = "\n".join(convo)
    return f"<s>[INST] <<SYS>>{sys_text}<</SYS>>\n{body} [/INST]"

# ----------------------------
# Output cleaner
# ----------------------------

def _clean_reply(text: str) -> str:
    if not text: return "(no reply)"
    lines = [ln.rstrip() for ln in text.splitlines()]
    if lines and re.match(r'^\s*(update|status|note)\b', lines[0], re.I):
        lines = lines[1:]
    out = "\n".join(lines).strip()
    return out or "(no reply)"

# ----------------------------
# Handoff for bot.py
# ----------------------------

def handle_message(source: str, text: str) -> str:
    global OPTS
    try:
        OPTS = _load_options()
        MEM.set_max_turns(OPTS["chatbot_history_turns"])
    except Exception:
        pass

    if not OPTS.get("chatbot_enabled", True):
        return ""

    chat_id = (source or "default").strip()
    user_msg = (text or "").strip()
    if not user_msg: return ""

    sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
    max_total = OPTS["chatbot_max_total_tokens"]
    reply_budget = OPTS["chatbot_reply_max_new_tokens"]

    history = MEM.get_context(chat_id)
    msgs: List[Tuple[str, str]] = [("system", sys_prompt)]
    for u, a in history:
        msgs.append(("user", u))
        msgs.append(("assistant", a))
    msgs.append(("user", user_msg))

    limit = max(256, max_total - reply_budget)
    while tokens_of_messages(msgs) > limit and history:
        history.pop(0)
        msgs = [("system", sys_prompt)]
        for u, a in history:
            msgs.append(("user", u))
            msgs.append(("assistant", a))
        msgs.append(("user", user_msg))

    if not _is_ready():
        return "LLM client not ready"

    try:
        raw = _LLM._do_generate(
            _build_prompt(msgs),
            timeout=None,       # let llm_client decide from llm_timeout_seconds
            base_url="",
            model_url="",
            model_name_hint="",
            max_tokens=reply_budget,
            with_grammar_auto=False
        )
        answer = _clean_reply(raw or "")
    except Exception as e:
        return f"LLM error: {e}"

    MEM.append_turn(chat_id, user_msg, answer)
    return answer