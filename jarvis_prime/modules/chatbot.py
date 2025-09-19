#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean Q&A, no riff banners, persona-free)
# - Reads chatbot_* options from /data/options.json
# - Uses llm_client.py to generate answers
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API via FastAPI if installed

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
    # Persona-free by default; set chat_system_prompt in options if you want one.
    "chat_system_prompt": "",
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

    out["chat_enabled"] = bool(raw.get("chatbot_enabled", raw.get("chat_enabled", True)))
    out["chat_history_turns"] = int(raw.get("chatbot_history_turns", raw.get("chat_history_turns", 3)))
    out["chat_max_total_tokens"] = int(raw.get("chatbot_max_total_tokens", raw.get("chat_max_total_tokens", 1200)))
    out["chat_reply_max_new_tokens"] = int(raw.get("chatbot_reply_max_new_tokens", raw.get("chat_reply_max_new_tokens", 256)))

    if isinstance(raw.get("chat_system_prompt"), str):
        out["chat_system_prompt"] = raw.get("chat_system_prompt", "").strip()

    if isinstance(raw.get("chat_model"), str):
        out["chat_model"] = raw.get("chat_model", "").strip()

    out["chat_history_turns"] = max(1, min(out["chat_history_turns"], DEFAULTS["chat_history_turns_max"]))
    return out

OPTS = _load_options()

# ----------------------------
# Token estimation (simple heuristic)
# ----------------------------

class _Tokenizer:
    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, (len(text) + 3) // 4)  # ~4 chars/token

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

# ----------------------------
# Prompt building (persona-free unless options provide text)
# ----------------------------

def _build_prompt_from_msgs(msgs: List[Tuple[str, str]]) -> str:
    """
    Convert (role, content) messages into a single prompt using the model's
    native chat format (Phi-style if detected; otherwise Llama [INST]).
    """
    # Detect Phi-style support
    if getattr(_LLM, "_is_phi3_family", None) and _LLM._is_phi3_family():
        buf: List[str] = []
        # Keep system messages if provided; otherwise omit system entirely
        sys_chunks = [c for (r, c) in msgs if r == "system" and c.strip()]
        if sys_chunks:
            buf.append(f"<|system|>\n{'\n\n'.join(sys_chunks)}\n<|end|>")
        for r, c in msgs:
            if r == "user":
                buf.append(f"<|user|>\n{c}\n<|end|>")
            elif r == "assistant":
                buf.append(f"<|assistant|>\n{c}\n<|end|>")
        buf.append("<|assistant|>\n")
        return "\n".join(buf)

    # Fallback: Llama [INST] format
    sys_chunks = [c for (r, c) in msgs if r == "system" and c.strip()]
    sys_text = f"<<SYS>>{'\n\n'.join(sys_chunks)}<</SYS>>\n" if sys_chunks else ""
    convo: List[str] = []
    for r, c in msgs:
        if r == "user":
            convo.append(f"User: {c}")
        elif r == "assistant":
            convo.append(f"Assistant: {c}")
    convo.append("Assistant:")
    body = "\n".join(convo)
    return f"<s>[INST] {sys_text}{body} [/INST]"

# ----------------------------
# Minimal banner stripper (first line only). No other cleaning.
# ----------------------------

_BANNER_RX = re.compile(
    r'^\s*(?:update|status|incident|digest|note)\s*[—:-].*(?:🚨|💥|🛰️)?\s*$',
    re.IGNORECASE
)

def _strip_leading_banner(text: str) -> str:
    if not text:
        return text
    lines = [ln.rstrip() for ln in text.splitlines()]
    if lines and (_BANNER_RX.match(lines[0]) or (len(lines[0]) <= 4 and any(x in lines[0] for x in ("🚨", "💥", "🛰️")))):
        return "\n".join(lines[1:]).strip()
    return "\n".join(lines).strip()

# ----------------------------
# Token-safe trimming
# ----------------------------

def _truncate_to_fit_user(sys_prompt: str, new_user: str, max_tokens: int) -> str:
    msgs = ([("system", sys_prompt)] if sys_prompt else []) + [("user", new_user)]
    if tokens_of_messages(msgs) <= max_tokens:
        return new_user
    lo, hi = 0, len(new_user)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = new_user[-mid:] if mid > 0 else ""
        msgs2 = ([("system", sys_prompt)] if sys_prompt else []) + [("user", candidate)]
        if tokens_of_messages(msgs2) <= max_tokens:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best if best else new_user[: max(0, len(new_user)//4)]

def _trim_to_budget(history: List[Tuple[str,str]], sys_prompt: str, new_user: str,
                    max_total_tokens: int, reply_budget: int) -> List[Tuple[str,str]]:
    limit = max(256, max_total_tokens - reply_budget)
    def pack(hist_pairs, utext):
        msgs: List[Tuple[str,str]] = []
        if sys_prompt:
            msgs.append(("system", sys_prompt))
        for u, a in hist_pairs:
            msgs.append(("user", u))
            msgs.append(("assistant", a))
        msgs.append(("user", utext))
        return msgs

    hist_copy = history[:]
    msgs = pack(hist_copy, new_user)
    guard = 0
    while tokens_of_messages(msgs) > limit and hist_copy:
        hist_copy.pop(0)          # drop oldest pair
        msgs = pack(hist_copy, new_user)
        guard += 1
        if guard > 512:
            break

    if tokens_of_messages(msgs) > limit:
        trimmed_user = _truncate_to_fit_user(sys_prompt, new_user, limit - 16)
        msgs = pack(hist_copy, trimmed_user)

    if tokens_of_messages(msgs) > limit:
        trimmed_user = _truncate_to_fit_user(sys_prompt, new_user, limit - 16)
        msgs = ([("system", sys_prompt)] if sys_prompt else []) + [("user", trimmed_user)]

    return msgs

# ----------------------------
# Generation with robust retries and smart fallback
# ----------------------------

def _gen_once(msgs: List[Tuple[str, str]], max_new_tokens: int, model_hint: str) -> str:
    _ensure_ready()
    prompt = _build_prompt_from_msgs(msgs)
    out = _LLM._do_generate(
        prompt,
        timeout=20,
        base_url="",
        model_url="",
        model_name_hint=model_hint or "",
        max_tokens=int(max_new_tokens),
        with_grammar_auto=False
    )
    return (out or "").strip()

def _generate_reply(msgs: List[Tuple[str, str]], reply_budget: int, model_hint: str) -> str:
    budgets = [reply_budget, max(128, reply_budget // 2), 64]
    for b in budgets:
        try:
            raw = _gen_once(msgs, b, model_hint=model_hint)
            out = _strip_leading_banner(raw)
            if out:
                return out
        except Exception:
            time.sleep(0.12)
            continue
    # Final guaranteed fallback (no echo)
    return "I couldn’t get a response from the model just now. Please try again or rephrase the question."

# ----------------------------
# Main handler
# ----------------------------

def handle_message(source: str, text: str) -> str:
    global OPTS
    # live refresh options & memory maxlen
    try:
        OPTS = _load_options()
        MEM.set_max_turns(int(OPTS.get("chat_history_turns", DEFAULTS["chat_history_turns"])))
    except Exception:
        pass

    if not OPTS.get("chat_enabled", True):
        return ""

    chat_id = (source or "default").strip() or "default"
    user_msg = (text or "").strip()
    if not user_msg:
        return ""

    sys_prompt = OPTS.get("chat_system_prompt", "").strip()
    max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
    reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
    model_hint = OPTS.get("chat_model", "")

    history = MEM.get_context(chat_id)
    msgs = _trim_to_budget(history, sys_prompt, user_msg, max_total, reply_budget)

    try:
        answer = _generate_reply(msgs, reply_budget, model_hint)
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
        reply = handle_message(payload.chat_id, payload.message)
        return ChatOut(
            chat_id=payload.chat_id,
            reply=reply,
            used_history_turns=len(MEM.get_context(payload.chat_id)),
            approx_context_tokens=tokens_of_messages(MEM.get_context(payload.chat_id)),
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
                reply = handle_message(chat_id, user_msg)
                await ws.send_json({
                    "chat_id": chat_id,
                    "reply": reply,
                    "used_history_turns": len(MEM.get_context(chat_id)),
                    "approx_context_tokens": tokens_of_messages(MEM.get_context(chat_id)),
                })
        except WebSocketDisconnect:
            return
        except Exception as e:
            await ws.send_json({"error": str(e)})
            await ws.close()

if __name__ == "__main__" and _FASTAPI_OK:
    import uvicorn
    uvicorn.run("chatbot:app", host="0.0.0.0", port=8189, reload=False)