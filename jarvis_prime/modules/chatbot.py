#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners)
# - Uses your existing llm_client.py (no changes needed there)
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

# ----------------------------
# Additive: fixed identity system prompt
# ----------------------------
_JARVIS_SYS_PROMPT = (
    "You are Jarvis Prime (Jarvis), a concise homelab assistant. "
    "Answer directly in clear sentences. No banners, no status headers, "
    "no preambles, no apologies, no policy talk. If asked your name, say Jarvis."
)

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
    "chat_system_prompt": "You are Jarvis Prime, a concise homelab assistant.",
    "chat_model": "",                      # optional override hint for Ollama name or gguf filename base
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

    # Optional extras if you ever add them:
    if isinstance(raw.get("chat_system_prompt"), str) and raw.get("chat_system_prompt", "").strip():
        out["chat_system_prompt"] = raw["chat_system_prompt"].strip()

    if isinstance(raw.get("chat_model"), str):
        out["chat_model"] = raw.get("chat_model", "").strip()

    # Enforce caps
    n = max(1, min(out["chat_history_turns"], DEFAULTS["chat_history_turns_max"]))
    out["chat_history_turns"] = n
    return out

OPTS = _load_options()

# ----------------------------
# ADDITIVE: tiny logger (stdout), toggle with JARVIS_CHATBOT_DEBUG=1
# ----------------------------
def _log(msg: str) -> None:
    if os.environ.get("JARVIS_CHATBOT_DEBUG", "0") == "1":
        print(f"[chatbot] {msg}", flush=True)

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
        # rough fallback
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
# LLM bridge (reuse llm_client)
# ----------------------------

try:
    import llm_client as _LLM
except Exception as _e:
    _LLM = None

# Borrow llm_client’s scrubbing helpers if present (will be refreshed if we lazy-import later)
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

# ADDITIVE: resilient, lazy import of llm_client if initial import failed
def _try_import_llm_client() -> bool:
    global _LLM, _scrub_meta, _scrub_pers, _strip_trans
    if _LLM is not None:
        return True
    try:
        import importlib
        _LLM = importlib.import_module("llm_client")
        _scrub_meta = getattr(_LLM, "_strip_meta_markers", None)
        _scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None)
        _strip_trans = getattr(_LLM, "_strip_transport_tags", None)
        _log("llm_client imported lazily")
        return True
    except Exception as e:
        _log(f"llm_client import failed: {e}")
        return False

def _is_ready() -> bool:
    if _LLM is not None:
        return True
    return _try_import_llm_client()

def _build_prompt_from_msgs(msgs: List[Tuple[str, str]]) -> str:
    """
    Convert (role, content) messages into a single prompt using the model's
    native chat format (Phi3-style if detected; otherwise Llama INST style).
    """
    if getattr(_LLM, "_is_phi3_family", None) and _LLM._is_phi3_family():
        # Phi-style chat template
        buf: List[str] = []
        sys_chunks = [c for (r, c) in msgs if r == "system"]
        sys_text = "\n\n".join(sys_chunks).strip() if sys_chunks else _JARVIS_SYS_PROMPT
        buf.append(f"<|system|>\n{sys_text}\n<|end|>")
        for r, c in msgs:
            if r == "user":
                buf.append(f"<|user|>\n{c}\n<|end|>")
            elif r == "assistant":
                buf.append(f"<|assistant|>\n{c}\n<|end|>")
        buf.append("<|assistant|>\n")
        return "\n".join(buf)

    # Fallback: Llama [INST] format
    sys_chunks = [c for (r, c) in msgs if r == "system"]
    sys_text = "\n\n".join(sys_chunks).strip() if sys_chunks else _JARVIS_SYS_PROMPT
    convo: List[str] = []
    for r, c in msgs:
        if r == "user":
            convo.append(f"User: {c}")
        elif r == "assistant":
            convo.append(f"Assistant: {c}")
    convo.append("Assistant:")
    body = "\n".join(convo)
    return f"<s>[INST] <<SYS>>{sys_text}<</SYS>>\n{body} [/INST]"

# ----------------------------
# Additive: robust generator with retries + salvage
# ----------------------------
def _gen_reply(msgs: List[Tuple[str, str]], max_new_tokens: int, model_hint: str = "") -> str:
    if not _is_ready():
        raise RuntimeError("llm_client not available")

    # Ensure a model is ready using your EnviroGuard profile settings
    _LLM.ensure_loaded()

    prompt = _build_prompt_from_msgs(msgs)

    # Try up to 3 normal attempts
    attempts = 0
    while attempts < 3:
        attempts += 1
        raw = _LLM._do_generate(
            prompt,
            timeout=45,  # a bit more headroom
            base_url="",           # resolved by ensure_loaded if Ollama is set in options
            model_url="",          # resolved from options
            model_name_hint=model_hint or "",
            max_tokens=int(max_new_tokens),
            with_grammar_auto=False
        ) or ""
        cleaned = _clean_reply(raw)
        if cleaned and cleaned != "(no reply)":
            first = cleaned.splitlines()[0] if '\n' in cleaned else cleaned
            if not _looks_like_banner(first):
                return cleaned
        time.sleep(0.05 * attempts)

    # ---- Last-chance salvage path: ask plainly with only the last user turn ----
    last_user = ""
    for r, c in reversed(msgs):
        if r == "user":
            last_user = c.strip()
            break
    if not last_user:
        return ""

    sys_chunks = [c for (r, c) in msgs if r == "system"]
    sys_text = "\n\n".join(sys_chunks).strip() if sys_chunks else _JARVIS_SYS_PROMPT

    salvage_msgs = [
        ("system", sys_text),
        ("user", f"{last_user}\n\nAnswer directly in 1–3 short paragraphs. No banners or headings.")
    ]
    salvage_prompt = _build_prompt_from_msgs(salvage_msgs)

    raw = _LLM._do_generate(
        salvage_prompt,
        timeout=45,
        base_url="",
        model_url="",
        model_name_hint=model_hint or "",
        max_tokens=int(max_new_tokens),
        with_grammar_auto=False
    ) or ""
    cleaned = _clean_reply(raw)
    return cleaned or raw or ""

# ----------------------------
# Output cleaner (strip riff headers / meta)
# ----------------------------

_BANNER_RX = re.compile(
    r'^\s*(?:update|status|incident|digest|note|report|telemetry)\s*[—:\-]\s.*?(?:[🚨💥🛰️🔥⚠️⭐✨✅❗️❗️]|\s*)\s*$',
    re.IGNORECASE
)

def _looks_like_banner(line: str) -> bool:
    if not line:
        return False
    if _BANNER_RX.match(line):
        return True
    if len(line) <= 6 and any(e in line for e in ("🚨","💥","🛰️","⚠️","🔥","✅","✨")):
        return True
    if re.match(r'^\s*updat[e]?\s*[—:\-–—]\s', line, re.I):
        return True
    return False

def _clean_reply(text: str) -> str:
    # Borrow llm_client scrubbers if available (they may be refreshed after lazy import)
    global _scrub_meta, _scrub_pers, _strip_trans
    if not text:
        return text
    lines = [ln.rstrip() for ln in text.splitlines()]
    if lines and _looks_like_banner(lines[0]):
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
# Handoff used by /app/bot.py
# ----------------------------

def handle_message(source: str, text: str) -> str:
    """Used by bot.py when a Gotify/ntfy title is 'chat' or 'talk'."""
    _log(f"handle_message enter source={source!r}, text_len={len(text or '')}")

    global OPTS
    try:
        OPTS = _load_options()
        MEM.set_max_turns(int(OPTS.get("chat_history_turns", DEFAULTS["chat_history_turns"])))
    except Exception as e:
        _log(f"options reload error: {e}")

    if not OPTS.get("chat_enabled", True):
        _log("chat disabled via options")
        return ""  # chatbot disabled; do nothing

    chat_id = (source or "default").strip() or "default"
    user_msg = (text or "").strip()
    if not user_msg:
        _log("empty user message")
        return ""

    sys_prompt = (OPTS.get("chat_system_prompt") or _JARVIS_SYS_PROMPT).strip()
    max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
    reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
    model_hint = OPTS.get("chat_model", "")

    msgs = MEM.trim_by_tokens(
        chat_id=chat_id,
        new_user=user_msg,
        sys_prompt=sys_prompt,
        max_total_tokens=max_total,
        reply_budget=reply_budget,
    )

    try:
        raw = _gen_reply(
            msgs=msgs,
            max_new_tokens=reply_budget,
            model_hint=model_hint
        )
        answer = _clean_reply(raw)
        if not answer:
            answer = "(no reply)"
    except Exception as e:
        _log(f"_gen_reply error: {e}")
        return f"LLM error: {e}"

    MEM.append_turn(chat_id, user_msg, answer)
    _log("handle_message exit ok")
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
        model: Optional[str] = Field(None, description="Override model hint (optional)")

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

        chat_id = (payload.chat_id or "default").strip() or "default"
        user_msg = (payload.message or "").strip()
        if not user_msg:
            raise HTTPException(status_code=400, detail="Empty message")

        sys_prompt = (OPTS.get("chat_system_prompt") or _JARVIS_SYS_PROMPT).strip()
        max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
        reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
        model_hint = payload.model or OPTS.get("chat_model", "")

        msgs = MEM.trim_by_tokens(
            chat_id=chat_id,
            new_user=user_msg,
            sys_prompt=sys_prompt,
            max_total_tokens=max_total,
            reply_budget=reply_budget,
        )

        try:
            raw = _gen_reply(msgs, reply_budget, model_hint=model_hint)
            answer = _clean_reply(raw)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM error: {e}")

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

                sys_prompt = (OPTS.get("chat_system_prompt") or _JARVIS_SYS_PROMPT).strip()
                max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
                reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
                model_hint = OPTS.get("chat_model", "")

                msgs = MEM.trim_by_tokens(
                    chat_id=chat_id,
                    new_user=user_msg,
                    sys_prompt=sys_prompt,
                    max_total_tokens=max_total,
                    reply_budget=reply_budget,
                )

                try:
                    raw = _gen_reply(msgs, reply_budget, model_hint=model_hint)
                    answer = _clean_reply(raw)
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

# Run API directly if FastAPI available
if __name__ == "__main__" and _FASTAPI_OK:
    import uvicorn
    uvicorn.run("chatbot:app", host="0.0.0.0", port=8189, reload=False)