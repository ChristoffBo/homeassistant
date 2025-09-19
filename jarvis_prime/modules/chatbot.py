#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (concise, riff-free answers)
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed
# - Post-processing removes riff/status headers and trims verbosity

import os
import json
import time
import re
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
    "chat_system_prompt": "You are Jarvis Prime. Answer directly and concisely. Put the result first; add one short reason if helpful.",
    "chat_model": "",
    # NEW knobs (optional, safe if absent)
    "chat_rewrite_enabled": True,          # run llm_client.rewrite on rambly answers
    "chat_rewrite_mood": "neutral",
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
    if isinstance(raw.get("chat_system_prompt"), str) and raw["chat_system_prompt"].strip():
        out["chat_system_prompt"] = raw["chat_system_prompt"].strip()
    if isinstance(raw.get("chat_model"), str):
        out["chat_model"] = raw.get("chat_model", "").strip()

    # Soft feature flags (safe if missing)
    out["chat_rewrite_enabled"] = bool(raw.get("chat_rewrite_enabled", DEFAULTS["chat_rewrite_enabled"]))
    if isinstance(raw.get("chat_rewrite_mood"), str) and raw["chat_rewrite_mood"].strip():
        out["chat_rewrite_mood"] = raw["chat_rewrite_mood"].strip()

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
        self.max_turns_default = n

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
# Answer post-processing
# ----------------------------

# Reuse scrubbers (local copies so we don't touch llm_client.py)
_PERSONA_TOKENS = ("dude","chick","nerd","rager","comedian","jarvis","ops","action","tappit","neutral")
_PERS_LEAD_SEQ_RX = re.compile(r'^(?:\s*(?:' + "|".join(_PERSONA_TOKENS) + r')\.\s*)+', flags=re.I)
_TRANSPORT_TAG_RX = re.compile(r'^\s*\[(smtp|proxy|http|https|gotify|webhook|apprise|ntfy|email|mailer|forward|poster)\]\s*', re.I)
_META_LINE_RX = re.compile(r'^\s*(\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\]|<<\s*/?\s*SYS\s*>>|</?s>)\s*$', re.I)
_RIFF_LEAD_RX = re.compile(r'^\s*(update|status|heads?[-\s]?up|alert|incident|note)\b[^\n]*$', re.I)
_LEXI_RX = re.compile(r'\bLexi\.\s*$', re.I)
_EMOJI_BANNER_RX = re.compile(r'^[\s\W]{0,6}[\u2600-\u27BF\U0001F300-\U0001FAFF].{0,8}$')

_BOILERPLATE_RX = re.compile(
    r'\b(as of my last update|i am unable to|i regret to inform you|as an ai|i cannot assist with)\b',
    re.I
)

def _strip_noise_lines(text: str) -> str:
    if not text:
        return ""
    lines = [ln.rstrip() for ln in text.splitlines()]
    cleaned = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            # collapse later
            cleaned.append(ln)
            continue
        if _TRANSPORT_TAG_RX.match(ln):    # [smtp]/[proxy] etc
            continue
        if _META_LINE_RX.match(ln):        # [SYSTEM] etc
            continue
        if _PERS_LEAD_SEQ_RX.match(ln):    # "jarvis. jarvis."
            continue
        if _RIFF_LEAD_RX.match(ln):        # "Update — …"
            continue
        if _LEXI_RX.search(ln):            # ends with "Lexi."
            continue
        if _EMOJI_BANNER_RX.match(ln):     # banner line full of emoji
            continue
        cleaned.append(ln)
    # collapse excess blank lines
    out = re.sub(r'\n{3,}', '\n\n', "\n".join(cleaned)).strip()
    return out

def _first_sentences(s: str, max_sents: int = 3) -> str:
    # grab up to N sentences, preferring short/direct ones
    parts = re.split(r'(?<=[.!?])\s+', s.strip())
    out = []
    for p in parts:
        if not p:
            continue
        out.append(p.strip())
        if len(out) >= max_sents:
            break
    return " ".join(out).strip()

def _polish_answer(raw: str, user_msg: str) -> str:
    s = (raw or "").strip().strip('`').strip()
    s = _strip_noise_lines(s)

    # remove boilerplate fillers
    s = _BOILERPLATE_RX.sub("", s)
    s = re.sub(r'\s{2,}', ' ', s).strip()

    # If multi-paragraph, prefer the first *content* paragraph (often the real answer)
    paras = [p.strip() for p in re.split(r'\n\s*\n', s) if p.strip()]
    if paras:
        s = paras[0]

    # Cap length to keep it sharp
    s = _first_sentences(s, max_sents=3)
    s = s[:700].rstrip()

    # Make sure we didn’t end up empty
    if not s:
        s = raw.strip()

    return s

# ----------------------------
# LLM adapter (supports many shapes)
# ----------------------------

def _call_llm_adapter(
    prompt: str,
    msgs: List[Tuple[str, str]],
    model: str,
    max_new_tokens: int,
) -> str:
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
            if r == "user": tmp_u = c
            elif r == "assistant" and tmp_u is not None:
                history_pairs.append((tmp_u, c))
                tmp_u = None
        return llm_client.generate_chat(
            prompt=prompt,
            history=history_pairs,
            model=model or None,
            max_new_tokens=max_new_tokens,
        )

    if hasattr(llm_client, "riff_once"):
        return llm_client.riff_once(context=prompt, timeout_s=20) or ""

    # LAST-RESORT: some builds only expose rewrite()/persona_riff(). Try rewrite(prompt)
    if hasattr(llm_client, "rewrite"):
        try:
            return llm_client.rewrite(text=prompt, mood="neutral", max_lines=0, max_chars=0)
        except Exception:
            pass

    raise RuntimeError("No supported llm_client function found (expected generate_reply / generate_chat / riff_once).")

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
    model = OPTS.get("chat_model", "")

    msgs = MEM.trim_by_tokens(
        chat_id=chat_id,
        new_user=user_msg,
        sys_prompt=sys_prompt,
        max_total_tokens=max_total,
        reply_budget=reply_budget,
    )

    try:
        raw = _call_llm_adapter(
            prompt=user_msg,
            msgs=msgs,
            model=model,
            max_new_tokens=reply_budget,
        )
    except Exception as e:
        return f"LLM error: {e}"

    # Clean & sharpen
    answer = _polish_answer(raw, user_msg)

    # Optional rewrite polish via llm_client.rewrite if answer still looks messy
    if OPTS.get("chat_rewrite_enabled", True):
        try:
            # heuristic: if it's long or still has boilerplate keywords, run a quick rewrite
            needs = (len(answer) > 420) or bool(_BOILERPLATE_RX.search(answer))
            if needs:
                import llm_client
                refined = llm_client.rewrite(
                    text=answer,
                    mood=OPTS.get("chat_rewrite_mood", "neutral"),
                    max_lines=0,
                    max_chars=600
                )
                refined = _polish_answer(refined, user_msg)
                if refined:
                    answer = refined
        except Exception:
            pass

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
            raise HTTPException(status_code=403, detail="Chat is disabled in options.json")

        chat_id = payload.chat_id.strip() or "default"
        user_msg = payload.message.strip()
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
            raw = _call_llm_adapter(user_msg, msgs, model, reply_budget)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM error: {e}")

        answer = _polish_answer(raw, user_msg)

        if OPTS.get("chat_rewrite_enabled", True):
            try:
                import llm_client
                needs = (len(answer) > 420) or bool(_BOILERPLATE_RX.search(answer))
                if needs:
                    refined = llm_client.rewrite(
                        text=answer,
                        mood=OPTS.get("chat_rewrite_mood", "neutral"),
                        max_lines=0,
                        max_chars=600
                    )
                    refined = _polish_answer(refined, user_msg)
                    if refined:
                        answer = refined
            except Exception:
                pass

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
                model = OPTS.get("chat_model", "")

                msgs = MEM.trim_by_tokens(
                    chat_id=chat_id,
                    new_user=user_msg,
                    sys_prompt=sys_prompt,
                    max_total_tokens=max_total,
                    reply_budget=reply_budget,
                )

                try:
                    raw = _call_llm_adapter(user_msg, msgs, model, reply_budget)
                except Exception as e:
                    await ws.send_json({"error": f"LLM error: {e}"})
                    continue

                answer = _polish_answer(raw, user_msg)

                if OPTS.get("chat_rewrite_enabled", True):
                    try:
                        import llm_client
                        needs = (len(answer) > 420) or bool(_BOILERPLATE_RX.search(answer))
                        if needs:
                            refined = llm_client.rewrite(
                                text=answer,
                                mood=OPTS.get("chat_rewrite_mood", "neutral"),
                                max_lines=0,
                                max_chars=600
                            )
                            refined = _polish_answer(refined, user_msg)
                            if refined:
                                answer = refined
                    except Exception:
                        pass

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