#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners, no extra config)
# - Uses llm_client.chat_generate (pure chat; respects llm_enabled, EnviroGuard)
# - No chatbot_* keys in options.json; calling this is the “switch”
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed

import os
import json
import time
import asyncio
import re
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque, defaultdict

# ----------------------------
# Zero-config constants (no chatbot_* in options.json)
# ----------------------------
HISTORY_TURNS = 3               # keep last N (user,assistant) pairs in memory
MAX_TOTAL_TOKENS = 1200         # rough budget for system+history+new user (excludes reply budget)
REPLY_MAX_NEW_TOKENS = 256      # max tokens to generate for the reply

# ----------------------------
# Token estimation (tiktoken optional)
# ----------------------------
class _Tokenizer:
    def __init__(self):
        self._enc = None
        try:
            import tiktoken  # type: ignore
            self._enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._enc = None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._enc:
            try:
                return len(self._enc.encode(text))
            except Exception:
                pass
        return max(1, (len(text) + 3) // 4)

TOKENIZER = _Tokenizer()

def tokens_of_messages(msgs: List[Tuple[str, str]]) -> int:
    total = 0
    for role, content in msgs:
        total += 4  # rough per-message overhead
        total += TOKENIZER.count(role) + TOKENIZER.count(content)
        total += 2
    return total

# ----------------------------
# Minimal in-memory chat store
# ----------------------------
class ChatMemory:
    def __init__(self, max_turns: int):
        self.max_turns_default = max_turns
        self.turns: Dict[str, Deque[Tuple[str, str]]] = defaultdict(lambda: deque(maxlen=self.max_turns_default))
        self.last_seen: Dict[str, float] = {}

    def append_turn(self, chat_id: str, user_msg: str, assistant_msg: str):
        dq = self.turns[chat_id]
        dq.append((user_msg, assistant_msg))
        self.last_seen[chat_id] = time.time()

    def get_context(self, chat_id: str) -> List[Tuple[str, str]]:
        return list(self.turns[chat_id])

    def set_max_turns(self, n: int):
        self.max_turns_default = n  # new deques get new maxlen

    def trim_by_tokens(
        self,
        chat_id: str,
        new_user: str,
        sys_prompt: str,
        max_total_tokens: int,
        reply_budget: int,
    ) -> List[Tuple[str, str]]:
        history = self.get_context(chat_id)
        msgs: List[Tuple[str, str]] = []
        if sys_prompt:
            msgs.append(("system", sys_prompt))
        for u, a in history:
            msgs.append(("user", u))
            msgs.append(("assistant", a))
        msgs.append(("user", new_user))

        limit = max(256, max_total_tokens - reply_budget)
        while tokens_of_messages(msgs) > limit and len(history) > 0:
            history.pop(0)
            msgs = []
            if sys_prompt:
                msgs.append(("system", sys_prompt))
            for u, a in history:
                msgs.append(("user", u))
                msgs.append(("assistant", a))
            msgs.append(("user", new_user))
        return msgs

    def GC(self, idle_seconds: int = 6 * 3600):
        now = time.time()
        drop = [cid for cid, ts in self.last_seen.items() if (now - ts) > idle_seconds]
        for cid in drop:
            self.turns.pop(cid, None)
            self.last_seen.pop(cid, None)

MEM = ChatMemory(max_turns=HISTORY_TURNS)

async def _bg_gc_loop():
    while True:
        await asyncio.sleep(1800)
        MEM.GC()

# ----------------------------
# LLM bridge (reuse llm_client.chat_generate)
# ----------------------------
try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _is_ready() -> bool:
    return _LLM is not None and hasattr(_LLM, "chat_generate")

def _gen_reply(messages_list: List[Dict[str, str]], max_new_tokens: int) -> str:
    if not _is_ready():
        raise RuntimeError("llm_client.chat_generate not available")
    # Pure chat path; leave system_prompt empty → llm_client loads /app/system_prompt.txt internally if present
    return _LLM.chat_generate(messages=messages_list, system_prompt="", max_new_tokens=max_new_tokens) or ""

# ----------------------------
# Output cleaner
# ----------------------------
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

_BANNER_RX = re.compile(
    r'^\s*(?:update|status|incident|digest|note)\s*[—:-].*(?:🚨|💥|🛰️)?\s*$',
    re.IGNORECASE
)

def _clean_reply(text: str) -> str:
    if not text:
        return text
    lines = [ln.rstrip() for ln in text.splitlines()]
    if lines and (_BANNER_RX.match(lines[0]) or (len(lines[0]) <= 4 and any(x in lines[0] for x in ("🚨","💥","🛰️")))):
        lines = lines[1:]
    out = "\n".join(lines).strip()
    if _strip_trans:
        out = _strip_trans(out)
    if _scrub_pers:
        out = _scrub_pers(out)
    if _scrub_meta:
        out = _scrub_meta(out)
    out = re.sub(r'(?is)^\s*i\s+regret\s+to\s+inform\s+you.*?(?:but|however)\s*,?\s*', '', out).strip()
    out = re.sub(r'\n{3,}', '\n\n', out).strip()
    return out

# ----------------------------
# Handoff for bot.py
# ----------------------------
def handle_message(source: str, text: str) -> str:
    # No chat_enabled flag — calling this is the “switch”.
    # If LLM is disabled or not loaded, llm_client.chat_generate returns "".
    MEM.set_max_turns(HISTORY_TURNS)

    chat_id = (source or "default").strip() or "default"
    user_msg = (text or "").strip()
    if not user_msg:
        return ""

    # We defer system prompt to llm_client (system_prompt="") so it uses /app/system_prompt.txt
    msgs_tuples = MEM.trim_by_tokens(
        chat_id=chat_id,
        new_user=user_msg,
        sys_prompt="",
        max_total_tokens=MAX_TOTAL_TOKENS,
        reply_budget=REPLY_MAX_NEW_TOKENS,
    )

    # Convert to structured chat format
    messages_list: List[Dict[str, str]] = [{"role": r, "content": c} for (r, c) in msgs_tuples]

    try:
        raw = _gen_reply(messages_list, REPLY_MAX_NEW_TOKENS)
        answer = _clean_reply(raw) or ""
    except Exception as e:
        return f"LLM error: {e}"

    MEM.append_turn(chat_id, user_msg, answer)
    return answer

# ----------------------------
# Optional FastAPI API
# ----------------------------
_FASTAPI_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Query
    from pydantic import BaseModel, Field
    _FASTAPI_OK = True
except Exception:
    pass

if _FASTAPI_OK:
    app = FastAPI(title="Jarvis Prime – Chat Lane")

    class ChatIn(BaseModel):
        chat_id: str
        message: str

    class ChatOut(BaseModel):
        chat_id: str
        reply: str
        used_history_turns: int
        approx_context_tokens: int

    @app.on_event("startup")
    async def _startup():
        asyncio.create_task(_bg_gc_loop())

    @app.post("/chat", response_model=ChatOut)
    async def chat_endpoint(payload: ChatIn, request: Request):
        chat_id = (payload.chat_id or "default").strip() or "default"
        user_msg = (payload.message or "").strip()
        if not user_msg:
            raise HTTPException(status_code=400, detail="Empty message")

        msgs_tuples = MEM.trim_by_tokens(
            chat_id=chat_id,
            new_user=user_msg,
            sys_prompt="",
            max_total_tokens=MAX_TOTAL_TOKENS,
            reply_budget=REPLY_MAX_NEW_TOKENS,
        )
        messages_list: List[Dict[str, str]] = [{"role": r, "content": c} for (r, c) in msgs_tuples]

        try:
            raw = _gen_reply(messages_list, REPLY_MAX_NEW_TOKENS)
            answer = _clean_reply(raw)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM error: {e}")

        MEM.append_turn(chat_id, user_msg, answer)
        return ChatOut(
            chat_id=chat_id,
            reply=answer,
            used_history_turns=len(MEM.get_context(chat_id)),
            approx_context_tokens=tokens_of_messages(msgs_tuples),
        )

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, chat_id: str = Query("default")):
        await ws.accept()
        try:
            while True:
                user_msg = (await ws.receive_text() or "").strip()
                if not user_msg:
                    await ws.send_json({"error": "empty message"})
                    continue

                msgs_tuples = MEM.trim_by_tokens(
                    chat_id=chat_id,
                    new_user=user_msg,
                    sys_prompt="",
                    max_total_tokens=MAX_TOTAL_TOKENS,
                    reply_budget=REPLY_MAX_NEW_TOKENS,
                )
                messages_list: List[Dict[str, str]] = [{"role": r, "content": c} for (r, c) in msgs_tuples]

                try:
                    raw = _gen_reply(messages_list, REPLY_MAX_NEW_TOKENS)
                    answer = _clean_reply(raw)
                except Exception as e:
                    await ws.send_json({"error": f"LLM error: {e}"})
                    continue

                MEM.append_turn(chat_id, user_msg, answer)
                await ws.send_json({
                    "chat_id": chat_id,
                    "reply": answer,
                    "used_history_turns": len(MEM.get_context(chat_id)),
                    "approx_context_tokens": tokens_of_messages(msgs_tuples),
                })
        except WebSocketDisconnect:
            return
        except Exception as e:
            try:
                await ws.send_json({"error": f"server error: {e}"})
            finally:
                await ws.close()

if __name__ == "__main__" and _FASTAPI_OK:
    import uvicorn
    uvicorn.run("chatbot:app", host="0.0.0.0", port=8189, reload=False)