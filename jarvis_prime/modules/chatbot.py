#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (clean chat, no riff banners)
# - Uses your existing llm_client.py (no changes needed there)
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed
#
# Additive upgrades in this version:
# - Strong token-safe trimming that never returns empty
# - Rebuild deques when chat_history_turns changes
# - Rolling summary of trimmed history (persona-free)
# - Persona-free enforcement (we never inject persona text)
# - Banner/transport/persona/meta scrub with safe fallback
# - One-shot retry with small backoff for transient LLM errors
# - Safe fallback reply only if model returns truly blank (no override of short answers)
# - Continuity bias: prefer to keep most-recent user turn

import os
import json
import time
import asyncio
import re
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
# LLM bridge (reuse llm_client)
# ----------------------------

try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _is_ready() -> bool:
    return _LLM is not None

# Optional helpers from llm_client (persona/meta/transport scrubbers)
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

def _ensure_ready():
    if not _is_ready():
        raise RuntimeError("llm_client not available")
    _LLM.ensure_loaded()

# ----------------------------
# Minimal in-memory chat store + rolling summaries
# ----------------------------

class ChatMemory:
    def __init__(self, max_turns: int):
        self.max_turns_default = max_turns
        self.turns: Dict[str, Deque[Tuple[str, str]]] = defaultdict(lambda: deque(maxlen=self.max_turns_default))
        self.last_seen: Dict[str, float] = {}
        self.summary: Dict[str, str] = {}

    def append_turn(self, chat_id: str, user_msg: str, assistant_msg: str):
        dq = self.turns[chat_id]
        dq.append((user_msg, assistant_msg))
        self.last_seen[chat_id] = time.time()

    def get_context(self, chat_id: str) -> List[Tuple[str, str]]:
        return list(self.turns[chat_id])

    def get_summary(self, chat_id: str) -> str:
        return self.summary.get(chat_id, "").strip()

    def set_summary(self, chat_id: str, text: str):
        self.summary[chat_id] = (text or "").strip()

    def set_max_turns(self, n: int):
        # Rebuild existing deques to the new maxlen (important if options change live)
        self.max_turns_default = max(1, int(n))
        for cid, old in list(self.turns.items()):
            newdq: Deque[Tuple[str, str]] = deque(old, maxlen=self.max_turns_default)
            self.turns[cid] = newdq

    def GC(self, idle_seconds: int = 6 * 3600):
        now = time.time()
        drop = [cid for cid, ts in self.last_seen.items() if (now - ts) > idle_seconds]
        for cid in drop:
            self.turns.pop(cid, None)
            self.last_seen.pop(cid, None)
            self.summary.pop(cid, None)

MEM = ChatMemory(max_turns=OPTS["chat_history_turns"])

async def _bg_gc_loop():
    while True:
        await asyncio.sleep(1800)
        MEM.GC()

# ----------------------------
# Prompt building
# ----------------------------

def _build_prompt_from_msgs(msgs: List[Tuple[str, str]], summary_note: str = "") -> str:
    """
    Convert (role, content) messages into a single prompt using the model's
    native chat format (Phi-style if detected; otherwise Llama INST style).
    We prepend a compact, persona-free 'Context Summary' if provided.
    """
    sys_chunks = [c for (r, c) in msgs if r == "system"]
    sys_text = "\n\n".join(sys_chunks).strip() if sys_chunks else "You are a helpful assistant."
    if summary_note:
        sys_text = f"{sys_text}\n\n[Context Summary]\n{summary_note}"

    if getattr(_LLM, "_is_phi3_family", None) and _LLM._is_phi3_family():
        buf: List[str] = []
        buf.append(f"<|system|>\n{sys_text}\n<|end|>")
        for r, c in msgs:
            if r == "user":
                buf.append(f"<|user|>\n{c}\n<|end|>")
            elif r == "assistant":
                buf.append(f"<|assistant|>\n{c}\n<|end|>")
        buf.append("<|assistant|>\n")
        return "\n".join(buf)

    # Fallback: Llama [INST] format
    convo: List[str] = []
    for r, c in msgs:
        if r == "user":
            convo.append(f"User: {c}")
        elif r == "assistant":
            convo.append(f"Assistant: {c}")
    convo.append("Assistant:")
    body = "\n".join(convo)
    return f"<s>[INST] <<SYS>>{sys_text}<</SYS>>\n{body} [/INST]"

def _gen_once(msgs: List[Tuple[str, str]], max_new_tokens: int, model_hint: str = "", summary_note: str = "") -> str:
    _ensure_ready()
    prompt = _build_prompt_from_msgs(msgs, summary_note=summary_note)
    out = _LLM._do_generate(
        prompt,
        timeout=20,            # EnviroGuard/llm_client may adjust internally
        base_url="",           # resolved by ensure_loaded if Ollama is set
        model_url="",          # resolved from options
        model_name_hint=model_hint or "",
        max_tokens=int(max_new_tokens),
        with_grammar_auto=False
    )
    return out or ""

def _gen_with_retry(msgs: List[Tuple[str, str]], max_new_tokens: int, model_hint: str = "", summary_note: str = "") -> str:
    """
    One-shot retry with small backoff for transient errors/timeouts.
    """
    try:
        return _gen_once(msgs, max_new_tokens, model_hint=model_hint, summary_note=summary_note)
    except Exception:
        # tiny backoff
        try:
            time.sleep(0.15)
            return _gen_once(msgs, max(max_new_tokens // 2, 64), model_hint=model_hint, summary_note=summary_note)
        except Exception as e2:
            raise e2

# ----------------------------
# Output cleaner (strip riff headers / meta)
# ----------------------------

_BANNER_RX = re.compile(
    r'^\s*(?:update|status|incident|digest|note)\s*[—:-].*(?:🚨|💥|🛰️)?\s*$',
    re.IGNORECASE
)

def _clean_reply(text: str) -> str:
    if not text:
        return text
    raw = text

    lines = [ln.rstrip() for ln in raw.splitlines()]
    # Drop 1-line banner if present
    if lines and (_BANNER_RX.match(lines[0]) or (len(lines[0]) <= 4 and any(x in lines[0] for x in ("🚨","💥","🛰️")))):
        lines = lines[1:]
    out = "\n".join(lines).strip()

    # Optional scrubs from llm_client; if they blank it out, fallback
    if _strip_trans:
        out = _strip_trans(out)
    if _scrub_pers:
        out = _scrub_pers(out)
    if _scrub_meta:
        out = _scrub_meta(out)

    # Remove common apology/policy preambles; collapse blank lines
    out = re.sub(r'(?is)^\s*i\s+regret\s+to\s+inform\s+you.*?(?:but|however)\s*,?\s*', '', out).strip()
    out = re.sub(r'\n{3,}', '\n\n', out).strip()

    if not out:
        out = "\n".join([ln for ln in raw.splitlines() if not _BANNER_RX.match(ln)]).strip()

    return out or "(no reply)"

def _safe_reply(raw: str, user_msg: str) -> str:
    """
    Never go silent: if the model returns truly blank after cleaning, produce a minimal,
    persona-free echo. Do NOT override short but valid answers.
    """
    out = _clean_reply(raw or "")
    if not out.strip():
        snippet = (user_msg[:120] + "...") if len(user_msg) > 120 else user_msg
        return f"(fallback) Got your message: {snippet}"
    return out

# ----------------------------
# Helpers for token-safe trimming
# ----------------------------

def _truncate_to_fit_user(sys_prompt: str, new_user: str, max_tokens: int) -> str:
    msgs = [("system", sys_prompt), ("user", new_user)]
    if tokens_of_messages(msgs) <= max_tokens:
        return new_user
    lo, hi = 0, len(new_user)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = new_user[-mid:] if mid > 0 else ""
        msgs2 = [("system", sys_prompt), ("user", candidate)]
        if tokens_of_messages(msgs2) <= max_tokens:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best if best else new_user[: max(0, len(new_user)//4)]

# ----------------------------
# Rolling summary generation (persona-free)
# ----------------------------

def _summarize_removed_turns(removed: List[Tuple[str, str]]) -> str:
    try:
        _ensure_ready()
    except Exception:
        return ""
    if not removed:
        return ""

    lines: List[str] = []
    for u, a in removed:
        u = u.strip()
        a = a.strip()
        if u:
            lines.append(f"User: {u}")
        if a:
            lines.append(f"Assistant: {a}")
    transcript = "\n".join(lines).strip()
    if not transcript:
        return ""

    prompt = (
        "Summarize the following chat snippets into 3–6 short factual bullet points. "
        "Keep it persona-free, no emojis, no fluff. Capture constraints, preferences, entities, and any unresolved question.\n\n"
        f"{transcript}\n\n"
        "Bullets:"
    )
    try:
        out = _LLM._do_generate(
            prompt,
            timeout=10,
            base_url="",
            model_url="",
            model_name_hint="",
            max_tokens=160,
            with_grammar_auto=False
        ) or ""
        out = re.sub(r'^\s*[-•]\s*', '• ', out.strip(), flags=re.M)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if len(lines) > 8:
            lines = lines[:8]
        return "\n".join(lines).strip()
    except Exception:
        return ""

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
    model_hint = OPTS.get("chat_model", "")

    msgs, removed = MEM.trim_by_tokens(
        chat_id=chat_id,
        new_user=user_msg,
        sys_prompt=sys_prompt,
        max_total_tokens=max_total,
        reply_budget=reply_budget,
        return_removed=True,
    )

    if removed:
        prev = MEM.get_summary(chat_id)
        add = _summarize_removed_turns(removed)
        if add:
            combined = (prev + ("\n" if prev else "") + add).strip()
            # keep the rolling summary compact
            if len(combined.splitlines()) > 20:
                combined = "\n".join(combined.splitlines()[-20:])
            MEM.set_summary(chat_id, combined)

    summary_note = MEM.get_summary(chat_id)

    try:
        raw = _gen_with_retry(
            msgs=msgs,
            max_new_tokens=reply_budget,
            model_hint=model_hint,
            summary_note=summary_note
        )
        answer = _safe_reply(raw, user_msg)
    except Exception as e:
        return f"LLM error: {e}"

    MEM.append_turn(chat_id, user_msg, answer)
    return answer

# ----------------------------
# Inject enhanced trim_by_tokens onto ChatMemory (additive)
# ----------------------------

def _chatmemory_trim_by_tokens(self,
    chat_id: str,
    new_user: str,
    sys_prompt: str,
    max_total_tokens: int,
    reply_budget: int,
    return_removed: bool = False,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Build messages within token budget, trimming oldest turns first.
    Guarantees at least: system + (trimmed if needed) latest user.
    Returns (msgs, removed_turns) if return_removed=True, else (msgs, []).
    Continuity bias: try to preserve the most recent user turn.
    """
    history = self.get_context(chat_id)
    removed: List[Tuple[str, str]] = []
    limit = max(256, max_total_tokens - reply_budget)

    hist_copy = history[:]

    def build_msgs(hist_pairs: List[Tuple[str,str]], utext: str) -> List[Tuple[str,str]]:
        msgs: List[Tuple[str,str]] = [("system", sys_prompt)]
        for u, a in hist_pairs:
            msgs.append(("user", u))
            msgs.append(("assistant", a))
        msgs.append(("user", utext))
        return msgs

    msgs = build_msgs(hist_copy, new_user)

    # Trim older turns first (FIFO)
    i = 0
    while tokens_of_messages(msgs) > limit and len(hist_copy) > 0:
        popped = hist_copy.pop(0)
        removed.append(popped)
        msgs = build_msgs(hist_copy, new_user)
        i += 1
        if i > 512:  # safety
            break

    # If still too large, trim the *new user* message
    if tokens_of_messages(msgs) > limit:
        trimmed_user = _truncate_to_fit_user(sys_prompt, new_user, limit - 16)
        msgs = build_msgs(hist_copy, trimmed_user)

    # Final hard stop: if still large, drop history entirely and keep trimmed user only
    if tokens_of_messages(msgs) > limit:
        trimmed_user = _truncate_to_fit_user(sys_prompt, new_user, limit - 16)
        msgs = [("system", sys_prompt), ("user", trimmed_user)]

    return (msgs, removed) if return_removed else (msgs, [])

# Bind the method (additive)
setattr(ChatMemory, "trim_by_tokens", _chatmemory_trim_by_tokens)

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

        sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
        max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
        reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
        model_hint = payload.model or OPTS.get("chat_model", "")

        msgs, removed = MEM.trim_by_tokens(
            chat_id=chat_id,
            new_user=user_msg,
            sys_prompt=sys_prompt,
            max_total_tokens=max_total,
            reply_budget=reply_budget,
            return_removed=True,
        )
        if removed:
            prev = MEM.get_summary(chat_id)
            add = _summarize_removed_turns(removed)
            if add:
                combined = (prev + ("\n" if prev else "") + add).strip()
                if len(combined.splitlines()) > 20:
                    combined = "\n".join(combined.splitlines()[-20:])
                MEM.set_summary(chat_id, combined)

        summary_note = MEM.get_summary(chat_id)

        try:
            raw = _gen_with_retry(msgs, reply_budget, model_hint=model_hint, summary_note=summary_note)
            answer = _safe_reply(raw, user_msg)
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

                sys_prompt = OPTS.get("chat_system_prompt", DEFAULTS["chat_system_prompt"])
                max_total = int(OPTS.get("chat_max_total_tokens", DEFAULTS["chat_max_total_tokens"]))
                reply_budget = int(OPTS.get("chat_reply_max_new_tokens", DEFAULTS["chat_reply_max_new_tokens"]))
                model_hint = OPTS.get("chat_model", "")

                msgs, removed = MEM.trim_by_tokens(
                    chat_id=chat_id,
                    new_user=user_msg,
                    sys_prompt=sys_prompt,
                    max_total_tokens=max_total,
                    reply_budget=reply_budget,
                    return_removed=True,
                )
                if removed:
                    prev = MEM.get_summary(chat_id)
                    add = _summarize_removed_turns(removed)
                    if add:
                        combined = (prev + ("\n" if prev else "") + add).strip()
                        if len(combined.splitlines()) > 20:
                            combined = "\n".join(combined.splitlines()[-20:])
                        MEM.set_summary(chat_id, combined)

                summary_note = MEM.get_summary(chat_id)

                try:
                    raw = _gen_with_retry(msgs, reply_budget, model_hint=model_hint, summary_note=summary_note)
                    answer = _safe_reply(raw, user_msg)
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
```0