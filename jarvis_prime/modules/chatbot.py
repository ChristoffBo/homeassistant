#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service
# - Small per-session memory (default 3 turns; cap via options.json)
# - Token-safe history trimming (tiktoken if installed; else 1 tok ≈ 4 chars)
# - HTTP:  POST /chat    (JSON in/out)
# - WS:    /ws?chat_id=...  (bi-directional)
# - Reuses existing llm_client if available via thin adapter
#
# Start (optional): uvicorn chatbot:app --host 0.0.0.0 --port 8189

import os
import json
import time
import asyncio
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque, defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Query
from pydantic import BaseModel, Field

# ----------------------------
# Config & Defaults
# ----------------------------

OPTIONS_PATH = "/data/options.json"   # HA add-on options (mounted persistent)
DEFAULTS = {
    "chat_enabled": True,               # master switch
    "chat_history_turns": 3,            # keep last N user+assistant exchanges
    "chat_history_turns_max": 5,        # hard upper guard
    "chat_max_total_tokens": 1200,      # total approx context budget (prompt+history+sys)
    "chat_reply_max_new_tokens": 256,   # assistant generation cap
    "chat_system_prompt": "You are Jarvis Prime, a concise homelab assistant.",
    "chat_model": "",                   # optional model hint to llm_client
}

def _merge_chatbot_aliases(opts: dict) -> dict:
    """
    Your add-on config.json exposes chatbot_* keys.
    This maps them to the chat_* keys this module uses internally.
    """
    out = dict(opts)
    # enable/disable
    if "chatbot_enabled" in opts:
        out["chat_enabled"] = bool(opts.get("chatbot_enabled"))
    # sizing
    if "chatbot_history_turns" in opts:
        out["chat_history_turns"] = int(opts.get("chatbot_history_turns", 3))
    if "chatbot_max_total_tokens" in opts:
        out["chat_max_total_tokens"] = int(opts.get("chatbot_max_total_tokens", 1200))
    if "chatbot_reply_max_new_tokens" in opts:
        out["chat_reply_max_new_tokens"] = int(opts.get("chatbot_reply_max_new_tokens", 256))
    # (optional) allow a system prompt override via llm_system_prompt if present
    sp = (opts.get("chat_system_prompt") or opts.get("llm_system_prompt") or "").strip()
    if sp:
        out["chat_system_prompt"] = sp
    # (optional) a model hint if the add-on exposes one
    if "chat_model" in opts:
        out["chat_model"] = str(opts.get("chat_model") or "")
    return out

def _load_options() -> dict:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = {}

    # Merge defaults (flat), then map chatbot_* -> chat_* so your config drives behavior.
    out = DEFAULTS.copy()
    out.update(_merge_chatbot_aliases(raw))

    # enforce hard caps
    try:
        n = int(out.get("chat_history_turns", 3))
        nmax = int(out.get("chat_history_turns_max", 5))
        out["chat_history_turns"] = max(1, min(n, nmax))
    except Exception:
        out["chat_history_turns"] = 3

    # sane floors
    try:
        out["chat_max_total_tokens"] = max(256, int(out.get("chat_max_total_tokens", 1200)))
    except Exception:
        out["chat_max_total_tokens"] = 1200
    try:
        out["chat_reply_max_new_tokens"] = max(8, int(out.get("chat_reply_max_new_tokens", 256)))
    except Exception:
        out["chat_reply_max_new_tokens"] = 256

    return out

OPTS = _load_options()

# ----------------------------
# Token estimation
# ----------------------------

class _Tokenizer:
    """Token counter using tiktoken if present, else chars/4 heuristic."""
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
        # Fallback heuristic: ~4 chars ≈ 1 token
        return max(1, (len(text) + 3) // 4)

TOKENIZER = _Tokenizer()

def tokens_of_messages(msgs: List[Tuple[str, str]]) -> int:
    """
    msgs: list of (role, content)
    """
    total = 0
    for role, content in msgs:
        total += 4  # small per-message overhead
        total += TOKENIZER.count(role) + TOKENIZER.count(content)
    total += 2  # closing priming
    return total

# ----------------------------
# Minimal in-memory chat store
# ----------------------------

class ChatMemory:
    """
    Per-chat_id ring buffer of last N exchanges.
    Each "turn" is a pair: user message and assistant reply.
    For trimming-by-tokens we may also drop oldest turns.
    """
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
        self.max_turns_default = n

    def trim_by_tokens(
        self,
        chat_id: str,
        new_user: str,
        sys_prompt: str,
        max_total_tokens: int,
        reply_budget: int,
    ) -> List[Tuple[str, str]]:
        """
        Build a (role, content) message list and trim oldest turns until it
        fits under (max_total_tokens - reply_budget).
        """
        history = self.get_context(chat_id)
        msgs: List[Tuple[str, str]] = [("system", sys_prompt)]
        for u, a in history:
            msgs.append(("user", u))
            msgs.append(("assistant", a))
        msgs.append(("user", new_user))

        limit = max(256, max_total_tokens - reply_budget)
        while tokens_of_messages(msgs) > limit and len(history) > 0:
            history.pop(0)  # drop oldest turn
            msgs = [("system", sys_prompt)]
            for u, a in history:
                msgs.append(("user", u))
                msgs.append(("assistant", a))
            msgs.append(("user", new_user))
        return msgs

    def GC(self, idle_seconds: int = 6 * 3600):
        now = time.time()
        drop: List[str] = []
        for cid, ts in self.last_seen.items():
            if (now - ts) > idle_seconds:
                drop.append(cid)
        for cid in drop:
            self.turns.pop(cid, None)
            self.last_seen.pop(cid, None)

MEM = ChatMemory(max_turns=OPTS["chat_history_turns"])

async def _bg_gc_loop():
    while True:
        await asyncio.sleep(1800)  # 30 min
        MEM.GC()

# ----------------------------
# LLM adapter (integrates llm_client)
# ----------------------------

def _call_llm_adapter(
    prompt: str,
    msgs: List[Tuple[str, str]],
    model: str,
    max_new_tokens: int,
) -> str:
    """
    Tries to call your existing /app/llm_client.py code. Two common patterns:
      - llm_client.generate_chat(prompt, history=[...], model="...", max_new_tokens=...)
      - llm_client.generate_reply(messages=[{"role":..., "content":...}, ...], model="...", max_new_tokens=...)
    """
    try:
        import llm_client
    except Exception as e:
        raise RuntimeError(f"llm_client not available: {e}")

    as_dict_msgs = [{"role": r, "content": c} for (r, c) in msgs]

    if hasattr(llm_client, "generate_reply"):
        return llm_client.generate_reply(
            messages=as_dict_msgs,
            model=model or None,
            max_new_tokens=max_new_tokens,
        )
    if hasattr(llm_client, "generate_chat"):
        history_pairs = []
        tmp_u = None
        for r, c in msgs:
            if r == "user":
                tmp_u = c
            elif r == "assistant" and tmp_u is not None:
                history_pairs.append((tmp_u, c))
                tmp_u = None
        return llm_client.generate_chat(
            prompt=prompt,
            history=history_pairs,
            model=model or None,
            max_new_tokens=max_new_tokens,
        )

    raise RuntimeError("No supported llm_client function found (expected generate_reply or generate_chat).")

# ----------------------------
# FastAPI app
# ----------------------------

app = FastAPI(title="Jarvis Prime – Chat Lane")

class ChatIn(BaseModel):
    chat_id: str = Field(..., description="Stable ID per chat session")
    message: str = Field(..., description="User input")
    model: Optional[str] = Field(None, description="Override model (optional)")

class ChatOut(BaseModel):
    chat_id: str
    reply: str
    used_history_turns: int
    approx_context_tokens: int

@app.on_event("startup")
async def _startup():
    global OPTS
    OPTS = _load_options()
    MEM.set_max_turns(OPTS["chat_history_turns"])
    asyncio.create_task(_bg_gc_loop())

@app.post("/chat", response_model=ChatOut)
async def chat_endpoint(payload: ChatIn, request: Request):
    if not OPTS.get("chat_enabled", True):
        raise HTTPException(status_code=403, detail="Chat is disabled by options.json (chatbot_enabled=False)")

    chat_id = (payload.chat_id or "default").strip() or "default"
    user_msg = (payload.message or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Empty message")

    sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
    max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
    reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
    model = payload.model or OPTS.get("chat_model", "")

    msgs = MEM.trim_by_tokens(
        chat_id=chat_id,
        new_user=user_msg,
        sys_prompt=sys_prompt,
        max_total_tokens=max_total,
        reply_budget=reply_budget,
    )

    try:
        answer = _call_llm_adapter(
            prompt=user_msg,
            msgs=msgs,
            model=model,
            max_new_tokens=reply_budget,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")

    MEM.append_turn(chat_id, user_msg, answer)

    return ChatOut(
        chat_id=chat_id,
        reply=answer,
        used_history_turns=len(MEM.get_context(chat_id)),
        approx_context_tokens=tokens_of_messages(msgs),
    )

# ----------------------------
# WebSocket chat
# ----------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, chat_id: str = Query("default")):
    if not OPTS.get("chat_enabled", True):
        await ws.close(code=4403)
        return

    await ws.accept()
    try:
        while True:
            user_msg = await ws.receive_text()
            user_msg = (user_msg or "").strip()
            if not user_msg:
                await ws.send_json({"error": "empty message"})
                continue

            sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
            max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
            reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
            model = OPTS.get("chat_model", "")

            msgs = MEM.trim_by_tokens(
                chat_id=chat_id,
                new_user=user_msg,
                sys_prompt=sys_prompt,
                max_total_tokens=max_total,
                reply_budget=reply_budget,
            )

            try:
                answer = _call_llm_adapter(
                    prompt=user_msg,
                    msgs=msgs,
                    model=model,
                    max_new_tokens=reply_budget,
                )
            except Exception as e:
                await ws.send_json({"error": f"LLM error: {e}"})
                continue

            MEM.append_turn(chat_id, user_msg, answer)
            await ws.send_json({
                "chat_id": chat_id,
                "reply": answer,
                "used_history_turns": len(MEM.get_context(chat_id)),
                "approx_context_tokens": tokens_of_messages(msgs),
            })

    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await ws.send_json({"error": f"server error: {e}"})
        finally:
            await ws.close()

# ----------------------------
# ADDITIVE: simple shim for bot.py handoff
# ----------------------------

def handle_message(source: str, text: str) -> str:
    """
    Minimal adapter so bot.py can call:
        reply = chatbot.handle_message(source="gotify", text="Hello")
    Respects chatbot_enabled (mapped to chat_enabled), uses ring-memory per source as chat_id.
    """
    try:
        # refresh options opportunistically (cheap)
        global OPTS
        OPTS = _load_options()
        MEM.set_max_turns(int(OPTS.get("chat_history_turns", DEFAULTS["chat_history_turns"])))
        if not OPTS.get("chat_enabled", True):
            return ""
    except Exception:
        pass

    chat_id = (source or "default").strip() or "default"
    user_msg = (text or "").strip()
    if not user_msg:
        return ""

    sys_prompt  = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
    max_total   = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
    reply_budget= int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
    model       = OPTS.get("chat_model", "")

    msgs = MEM.trim_by_tokens(
        chat_id=chat_id,
        new_user=user_msg,
        sys_prompt=sys_prompt,
        max_total_tokens=max_total,
        reply_budget=reply_budget,
    )

    try:
        answer = _call_llm_adapter(
            prompt=user_msg,
            msgs=msgs,
            model=model,
            max_new_tokens=reply_budget,
        )
    except Exception as e:
        return f"LLM error: {e}"

    MEM.append_turn(chat_id, user_msg, answer)
    return answer