#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean Q&A, no riff, no persona)
# - Reads chatbot_* options from /data/options.json (+ llm_timeout_seconds)
# - Uses llm_client.py to generate answers (only _do_generate, unchanged)
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API via FastAPI if installed
#
# Additive fixes:
# - Token-budgeted history trim (drops oldest pairs first)
# - One-shot retry with shorter timeout & fewer tokens
# - Uses llm_timeout_seconds from options.json when present
# - Safer cleaning; never returns empty

import os
import json
import time
import asyncio
import re
from collections import deque, defaultdict
from typing import Deque, Dict, List, Optional, Tuple

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
    "chat_system_prompt": "You are Jarvis Prime, a concise homelab assistant.",
    "chat_model": "",
    "llm_timeout_seconds": 20,   # additive: default if not in options.json
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

    # map old chatbot_* keys if present
    out["chat_enabled"] = bool(raw.get("chatbot_enabled", raw.get("chat_enabled", True)))
    out["chat_history_turns"] = int(raw.get("chatbot_history_turns", raw.get("chat_history_turns", DEFAULTS["chat_history_turns"])))
    out["chat_max_total_tokens"] = int(raw.get("chatbot_max_total_tokens", raw.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"])))
    out["chat_reply_max_new_tokens"] = int(raw.get("chatbot_reply_max_new_tokens", raw.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"])))
    out["llm_timeout_seconds"] = int(raw.get("llm_timeout_seconds", DEFAULTS["llm_timeout_seconds"]))

    if isinstance(raw.get("chat_system_prompt"), str) and raw["chat_system_prompt"].strip():
        out["chat_system_prompt"] = raw["chat_system_prompt"].strip()
    if isinstance(raw.get("chat_model"), str):
        out["chat_model"] = raw.get("chat_model", "").strip()

    # caps
    out["chat_history_turns"] = max(1, min(out["chat_history_turns"], DEFAULTS["chat_history_turns_max"]))
    # reply cap reasonable floor/ceiling
    out["chat_reply_max_new_tokens"] = max(32, min(out["chat_reply_max_new_tokens"], 1024))
    # total cap floor
    out["chat_max_total_tokens"] = max(256, out["chat_max_total_tokens"])
    return out

OPTS = _load_options()

# ----------------------------
# Token estimation (simple)
# ----------------------------

class _Tokenizer:
    def __init__(self):
        self._enc = None
        try:
            import tiktoken  # optional
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
        # heuristic ~4 chars/token
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
# Memory
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
        n = max(1, int(n))
        self.max_turns_default = n
        for cid, old in list(self.turns.items()):
            self.turns[cid] = deque(old, maxlen=n)

    def GC(self, idle_seconds: int = 6 * 3600):
        now = time.time()
        drop = [cid for cid, ts in self.last_seen.items() if now - ts > idle_seconds]
        for cid in drop:
            self.turns.pop(cid, None)
            self.last_seen.pop(cid, None)

MEM = ChatMemory(max_turns=OPTS["chat_history_turns"])

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

def _ensure_ready():
    if not _LLM:
        raise RuntimeError("llm_client not available")
    _LLM.ensure_loaded()

# optional scrubbers if present in llm_client (no-ops if missing)
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_is_phi3 = getattr(_LLM, "_is_phi3_family", None) if _LLM else None

def _build_prompt(msgs: List[Tuple[str, str]], sys_prompt: str) -> str:
    # Phi-style if supported
    if callable(_is_phi3) and _is_phi3():
        buf: List[str] = [f"<|system|>\n{sys_prompt}\n<|end|>"]
        for r, c in msgs:
            if r == "user":
                buf.append(f"<|user|>\n{c}\n<|end|>")
            elif r == "assistant":
                buf.append(f"<|assistant|>\n{c}\n<|end|>")
        buf.append("<|assistant|>\n")
        return "\n".join(buf)
    # Llama INST fallback
    convo = []
    for r, c in msgs:
        if r == "user":
            convo.append(f"User: {c}")
        elif r == "assistant":
            convo.append(f"Assistant: {c}")
    convo.append("Assistant:")
    return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n" + "\n".join(convo) + " [/INST]"

def _gen_reply_once(prompt: str, timeout_s: int, max_new_tokens: int, model_hint: str) -> str:
    _ensure_ready()
    out = _LLM._do_generate(
        prompt,
        timeout=int(max(4, timeout_s)),
        base_url="",
        model_url="",
        model_name_hint=model_hint or "",
        max_tokens=int(max_new_tokens),
        with_grammar_auto=False
    )
    return out or ""

def _gen_reply_with_retry(prompt: str, timeout_s: int, max_new_tokens: int, model_hint: str) -> str:
    # first attempt
    txt = _gen_reply_once(prompt, timeout_s, max_new_tokens, model_hint)
    if txt.strip():
        return txt
    # quick backoff retry: shorter timeout, fewer tokens
    try:
        time.sleep(0.15)
    except Exception:
        pass
    return _gen_reply_once(prompt, max(4, timeout_s // 2), max(64, max_new_tokens // 2), model_hint)

# ----------------------------
# Cleaning
# ----------------------------

_BANNER_RX = re.compile(r'^\s*(update|status|incident|digest|note)\s*[:—-].*$', re.I)

def _clean_reply(text: str) -> str:
    if not text:
        return ""
    raw = text

    # drop 1st-line banners like "Update: ..."
    lines = [ln.rstrip() for ln in raw.splitlines()]
    if lines and (_BANNER_RX.match(lines[0]) or (len(lines[0]) <= 4 and any(x in lines[0] for x in ("🚨", "💥", "🛰️")))):
        lines = lines[1:]
    out = "\n".join(lines).strip()

    # optional scrubbers if available
    if _strip_trans:
        out = _strip_trans(out)
    if _scrub_pers:
        out = _scrub_pers(out)
    if _scrub_meta:
        out = _scrub_meta(out)

    # collapse blank lines, keep something
    out = re.sub(r'\n{3,}', '\n\n', out).strip()
    return out

def _safe_reply(raw: str, user_msg: str) -> str:
    out = _clean_reply(raw or "")
    if not out:
        snippet = (user_msg[:120] + "...") if len(user_msg) > 120 else user_msg
        return f"(fallback) Got your message: {snippet}"
    if len(out.split()) < 3:
        return out + " (please expand)"
    return out

# ----------------------------
# History trim to fit token budget
# ----------------------------

def _trim_history_to_budget(sys_prompt: str, history: List[Tuple[str, str]], new_user: str, max_total_tokens: int, reply_budget: int) -> List[Tuple[str, str]]:
    """
    Keep: system + (some) history + new user, within (max_total_tokens - reply_budget).
    Drops oldest pairs first. Final guarantee: system + new user.
    """
    limit = max(256, max_total_tokens - max(64, reply_budget))
    def build(hist_pairs: List[Tuple[str,str]], utext: str) -> List[Tuple[str,str]]:
        msgs: List[Tuple[str,str]] = [("system", sys_prompt)]
        for u, a in hist_pairs:
            msgs.append(("user", u))
            msgs.append(("assistant", a))
        msgs.append(("user", utext))
        return msgs

    hist_copy = history[:]
    msgs = build(hist_copy, new_user)

    # drop oldest until it fits
    guard = 0
    while tokens_of_messages(msgs) > limit and hist_copy and guard < 256:
        hist_copy.pop(0)
        msgs = build(hist_copy, new_user)
        guard += 1

    # if still too large, truncate user tail
    if tokens_of_messages(msgs) > limit:
        # binary chop new_user tail to fit roughly
        lo, hi = 0, len(new_user)
        best = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = new_user[-mid:] if mid > 0 else ""
            test = build(hist_copy, cand)
            if tokens_of_messages(test) <= limit:
                best = cand
                lo = mid + 1
            else:
                hi = mid - 1
        msgs = build(hist_copy, best)

    # last resort: system + (possibly empty) user
    if tokens_of_messages(msgs) > limit:
        # keep only system + tail slice of new user
        tail = new_user[-max(8, len(new_user)//4):]
        msgs = [("system", sys_prompt), ("user", tail)]
    return msgs

# ----------------------------
# Main handler
# ----------------------------

def handle_message(source: str, text: str) -> str:
    """
    NOTE: keep this synchronous (bot.py expects a plain return, not coroutine)
    """
    global OPTS
    OPTS = _load_options()
    MEM.set_max_turns(OPTS["chat_history_turns"])

    if not OPTS.get("chat_enabled", True):
        return ""

    chat_id = (source or "default").strip() or "default"
    user_msg = (text or "").strip()
    if not user_msg:
        return ""

    sys_prompt = OPTS["chat_system_prompt"]
    reply_budget = int(OPTS["chat_reply_max_new_tokens"])
    model_hint = OPTS["chat_model"]
    max_total = int(OPTS["chat_max_total_tokens"])
    gen_timeout = int(OPTS.get("llm_timeout_seconds", DEFAULTS["llm_timeout_seconds"]))

    history = MEM.get_context(chat_id)
    msgs = _trim_history_to_budget(sys_prompt, history, user_msg, max_total, reply_budget)
    prompt = _build_prompt(msgs, sys_prompt)

    try:
        raw = _gen_reply_with_retry(prompt, gen_timeout, reply_budget, model_hint)
        answer = _safe_reply(raw, user_msg)
    except Exception as e:
        answer = f"LLM error: {e}"

    MEM.append_turn(chat_id, user_msg, answer)
    return answer

# ----------------------------
# Optional HTTP/WS API
# ----------------------------

_FASTAPI_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Query
    from pydantic import BaseModel
    _FASTAPI_OK = True
except Exception:
    pass

if _FASTAPI_OK:
    app = FastAPI(title="Jarvis Prime – Chat Lane")

    class ChatIn(BaseModel):
        chat_id: str
        message: str
        model: Optional[str] = None

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
        if not OPTS.get("chat_enabled", True):
            raise HTTPException(status_code=403, detail="Chat disabled")

        chat_id = (payload.chat_id or "default").strip() or "default"
        msg = (payload.message or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="Empty message")

        # build msgs here too so approx_context_tokens reflects actual prompt
        sys_prompt = OPTS["chat_system_prompt"]
        reply_budget = int(OPTS["chat_reply_max_new_tokens"])
        max_total = int(OPTS["chat_max_total_tokens"])
        history = MEM.get_context(chat_id)
        msgs = _trim_history_to_budget(sys_prompt, history, msg, max_total, reply_budget)

        reply = handle_message(chat_id, msg)
        return ChatOut(
            chat_id=chat_id,
            reply=reply,
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
                    await ws.send_json({"error": "empty"})
                    continue
                # compute approx tokens like REST
                sys_prompt = OPTS["chat_system_prompt"]
                reply_budget = int(OPTS["chat_reply_max_new_tokens"])
                max_total = int(OPTS["chat_max_total_tokens"])
                history = MEM.get_context(chat_id)
                msgs = _trim_history_to_budget(sys_prompt, history, user_msg, max_total, reply_budget)

                reply = handle_message(chat_id, user_msg)
                await ws.send_json({
                    "chat_id": chat_id,
                    "reply": reply,
                    "used_history_turns": len(MEM.get_context(chat_id)),
                    "approx_context_tokens": tokens_of_messages(msgs),
                })
        except WebSocketDisconnect:
            return
        except Exception as e:
            await ws.send_json({"error": str(e)})
            await ws.close()

if __name__ == "__main__" and _FASTAPI_OK:
    import uvicorn
    uvicorn.run("chatbot:app", host="0.0.0.0", port=8189, reload=False)