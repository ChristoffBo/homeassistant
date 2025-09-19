#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (works with llm_client.py as-is)
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed

import os
import json
import time
import asyncio
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque, defaultdict

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
    "chat_system_prompt": "You are Jarvis Prime, a concise homelab assistant. Answer factually and directly. If unsure, say so.",
    "chat_model": "",
}

def _load_options_raw() -> dict:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _load_options() -> dict:
    raw = _load_options_raw()
    out = DEFAULTS.copy()

    # Map your schema (chatbot_*) → internal (chat_*)
    out["chat_enabled"] = bool(raw.get("chatbot_enabled", raw.get("chat_enabled", True)))
    out["chat_history_turns"] = int(raw.get("chatbot_history_turns", raw.get("chat_history_turns", 3)))
    out["chat_max_total_tokens"] = int(raw.get("chatbot_max_total_tokens", raw.get("chat_max_total_tokens", 1200)))
    out["chat_reply_max_new_tokens"] = int(raw.get("chatbot_reply_max_new_tokens", raw.get("chat_reply_max_new_tokens", 256)))

    # Optional extras
    v = raw.get("chat_system_prompt")
    if isinstance(v, str) and v.strip():
        out["chat_system_prompt"] = v.strip()

    v = raw.get("chat_model")
    if isinstance(v, str):
        out["chat_model"] = v.strip()

    # Enforce caps
    n = max(1, min(out["chat_history_turns"], DEFAULTS["chat_history_turns_max"]))
    out["chat_history_turns"] = n
    return out

OPTS = _load_options()

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
        self.max_turns_default = n  # new deques will pick this up

    def trim_by_tokens(
        self,
        chat_id: str,
        new_user: str,
        sys_prompt: str,
        max_total_tokens: int,
        reply_budget: int,
    ) -> List[Tuple[str, str]]:
        history = self.get_context(chat_id)
        msgs: List[Tuple[str, str]] = [("system", sys_prompt)]
        for u, a in history:
            msgs.append(("user", u))
            msgs.append(("assistant", a))
        msgs.append(("user", new_user))

        limit = max(256, max_total_tokens - reply_budget)
        while tokens_of_messages(msgs) > limit and len(history) > 0:
            history.pop(0)
            msgs = [("system", sys_prompt)]
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

MEM = ChatMemory(max_turns=OPTS["chat_history_turns"])

async def _bg_gc_loop():
    while True:
        await asyncio.sleep(1800)
        MEM.GC()

# ----------------------------
# LLM chat via llm_client (no changes to llm_client.py)
# ----------------------------

def _build_chat_prompt_phi(msgs: List[Tuple[str, str]]) -> str:
    """Phi-family chat template."""
    parts = []
    for role, content in msgs:
        tag = "system" if role == "system" else "user" if role == "user" else "assistant"
        parts.append(f"<|{tag}|>\n{content}\n<|end|>")
    # ensure we end at assistant to request completion
    if not msgs or msgs[-1][0] != "assistant":
        parts.append("<|assistant|>\n")
    return "\n".join(parts)

def _build_chat_prompt_instruct(msgs: List[Tuple[str, str]]) -> str:
    """Llama '[INST]' style as a safe fallback."""
    sys = ""
    turns: List[Tuple[str, str]] = []
    cur_user = ""
    for role, content in msgs:
        if role == "system":
            sys = content.strip()
        elif role == "user":
            cur_user = content
        elif role == "assistant":
            turns.append((cur_user, content))
            cur_user = ""
    # last dangling user (current question)
    if cur_user:
        turns.append((cur_user, ""))

    def wrap(u: str, a: str) -> str:
        if a:
            return f"<s>[INST] <<SYS>>{sys}<</SYS>>\n{u} [/INST]{a}</s>"
        else:
            return f"<s>[INST] <<SYS>>{sys}<</SYS>>\n{u} [/INST]"

    out = []
    for u, a in turns:
        out.append(wrap(u, a))
    if out:
        if out[-1].endswith("</s>"):
            # ask for a new completion; append an empty assistant slot
            out.append(f"<s>[INST] <<SYS>>{sys}<</SYS>>\n{turns[-1][0]} [/INST]")
    else:
        out.append(f"<s>[INST] <<SYS>>{sys}<</SYS>>\n[/INST]")
    return "\n".join(out)

def _call_llm_chat(
    msgs: List[Tuple[str, str]],
    max_new_tokens: int,
) -> str:
    # Import llm_client and use its public loader + internal helpers
    try:
        import llm_client as lc
    except Exception as e:
        return f"LLM error: llm_client not available: {e}"

    # Make sure a model (or Ollama) is ready
    try:
        if lc.LLM_MODE == "none":
            lc.ensure_loaded()  # resolve from options
    except Exception as e:
        return f"LLM error: ensure_loaded failed: {e}"

    # Choose template based on model family
    try:
        is_phi = lc._is_phi3_family()
    except Exception:
        is_phi = True  # safest default for your models

    prompt = _build_chat_prompt_phi(msgs) if is_phi else _build_chat_prompt_instruct(msgs)

    # Pull profile timeout from llm_client
    try:
        _, _, _, prof_timeout = lc._current_profile()
        timeout = max(4, int(prof_timeout or 20))
    except Exception:
        timeout = 20

    try:
        txt = lc._do_generate(
            prompt,
            timeout=timeout,
            base_url="",            # resolved inside llm_client
            model_url="",
            model_name_hint="",
            max_tokens=int(max_new_tokens),
            with_grammar_auto=False
        )
        # Clean any meta markers using lc's utility if present
        try:
            txt = lc._strip_meta_markers(txt)
        except Exception:
            pass
        return (txt or "").strip()
    except Exception as e:
        return f"LLM error: {e}"

# ----------------------------
# Handoff used by /app/bot.py
# ----------------------------

def handle_message(source: str, text: str) -> str:
    """Used by bot.py when a Gotify/ntfy title is 'chat' or 'talk'."""
    global OPTS
    try:
        OPTS = _load_options()
        MEM.set_max_turns(int(OPTS.get("chat_history_turns", DEFAULTS["chat_history_turns"])))
    except Exception:
        pass

    if not OPTS.get("chat_enabled", True):
        return ""  # chatbot disabled; do nothing

    chat_id = (source or "default").strip() or "default"
    user_msg = (text or "").strip()
    if not user_msg:
        return ""

    sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
    max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
    reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))

    msgs = MEM.trim_by_tokens(
        chat_id=chat_id,
        new_user=user_msg,
        sys_prompt=sys_prompt,
        max_total_tokens=max_total,
        reply_budget=reply_budget,
    )

    answer = _call_llm_chat(msgs=msgs, max_new_tokens=reply_budget)

    # If model produced nothing, fail soft
    if not isinstance(answer, str):
        answer = str(answer or "")
    answer = answer.strip()
    if not answer:
        answer = "Sorry — I couldn’t generate a reply."

    MEM.append_turn(chat_id, user_msg, answer)
    return answer

# ----------------------------
# Optional HTTP/WS API (only if FastAPI installed)
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
        chat_id: str = Field(..., description="Stable ID per chat session")
        message: str = Field(..., description="User input")

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
            raise HTTPException(status_code=403, detail="Chat is disabled in options.json")

        chat_id = payload.chat_id.strip() or "default"
        user_msg = payload.message.strip()
        if not user_msg:
            raise HTTPException(status_code=400, detail="Empty message")

        sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
        max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
        reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))

        msgs = MEM.trim_by_tokens(
            chat_id=chat_id,
            new_user=user_msg,
            sys_prompt=sys_prompt,
            max_total_tokens=max_total,
            reply_budget=reply_budget,
        )

        answer = _call_llm_chat(msgs=msgs, max_new_tokens=reply_budget)
        if not answer:
            raise HTTPException(status_code=500, detail="LLM returned empty reply")

        MEM.append_turn(chat_id, user_msg, answer)
        return ChatOut(
            chat_id=chat_id,
            reply=answer,
            used_history_turns=len(MEM.get_context(chat_id)),
            approx_context_tokens=tokens_of_messages(msgs),
        )

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, chat_id: str = Query("default")):
        if not OPTS.get("chat_enabled", True):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            while True:
                user_msg = (await ws.receive_text() or "").strip()
                if not user_msg:
                    await ws.send_json({"error": "empty message"})
                    continue

                sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
                max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
                reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))

                msgs = MEM.trim_by_tokens(
                    chat_id=chat_id,
                    new_user=user_msg,
                    sys_prompt=sys_prompt,
                    max_total_tokens=max_total,
                    reply_budget=reply_budget,
                )

                answer = _call_llm_chat(msgs=msgs, max_new_tokens=reply_budget)
                if not answer:
                    await ws.send_json({"error": "LLM empty reply"})
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

# If you ever want to run the API directly (only when FastAPI is present):
if __name__ == "__main__" and _FASTAPI_OK:
    import uvicorn
    uvicorn.run("chatbot:app", host="0.0.0.0", port=8189, reload=False)