#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (CLEAN CHAT ONLY)
# - No riff/persona formatting
# - Uses llm_client.ensure_loaded() and internal generator for direct answers
# - Reads chatbot_* options from /data/options.json
# - Exposes handle_message(source, text) for bot.py handoff
# - Optional HTTP/WS API if FastAPI is installed

import os
import json
import time
import asyncio
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque, defaultdict

OPTIONS_PATH = "/data/options.json"

DEFAULTS = {
    "chat_enabled": True,                  # mapped from chatbot_enabled
    "chat_history_turns": 3,               # mapped from chatbot_history_turns
    "chat_history_turns_max": 5,
    "chat_max_total_tokens": 1200,         # mapped from chatbot_max_total_tokens
    "chat_reply_max_new_tokens": 256,      # mapped from chatbot_reply_max_new_tokens
    "chat_system_prompt": "You are Jarvis Prime, a concise homelab assistant. Answer the user's question directly and helpfully. If you don't know, say so plainly.",
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

    if isinstance(raw.get("chat_system_prompt"), str) and raw["chat_system_prompt"].strip():
        out["chat_system_prompt"] = raw["chat_system_prompt"].strip()
    if isinstance(raw.get("chat_model"), str):
        out["chat_model"] = raw.get("chat_model", "").strip()

    n = max(1, min(out["chat_history_turns"], DEFAULTS["chat_history_turns_max"]))
    out["chat_history_turns"] = n
    return out

OPTS = _load_options()

# ----------------------------
# Token estimation
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
# LLM bridge (uses llm_client directly)
# ----------------------------
def _build_chat_prompt(sys_prompt: str, msgs: List[Tuple[str, str]]) -> str:
    """
    Build a Phi-3 style prompt if available; otherwise fall back to Llama Instruct format.
    """
    import llm_client as LC
    # Assemble one system + alternating user/assistant
    sys = sys_prompt.strip()
    parts_phi = [f"<|system|>\n{sys}\n<|end|>"]
    parts_llama = [f"<s>[INST] <<SYS>>{sys}<</SYS>>\n"]

    idx = 0
    for role, content in msgs:
        if role == "system":
            continue
        if role == "user":
            parts_phi.append(f"<|user|>\n{content}\n<|end|>")
            if idx == 0:
                parts_llama.append(f"{content} [/INST]")
            else:
                parts_llama.append(f"\n<s>[INST] {content} [/INST]")
            idx += 1
        elif role == "assistant":
            parts_phi.append(f"<|assistant|>\n{content}\n<|end|>")
            # Llama instruct usually doesn’t include assistant echoes between INST blocks

    # Always end with assistant cue
    parts_phi.append("<|assistant|>\n")
    phi_prompt = "\n".join(parts_phi)
    llama_prompt = "\n".join(parts_llama)
    return phi_prompt if getattr(LC, "_is_phi3_family")() else llama_prompt

def _generate_llm(answer_prompt: str, max_new_tokens: int) -> str:
    import llm_client as LC
    # Make sure model is loaded (resolves from options)
    LC.ensure_loaded()
    # Use the client’s internal generator so it handles ollama/llama paths & stops
    # Timeout follows EnviroGuard profile (inside llm_client)
    try:
        text = LC._do_generate(
            answer_prompt,
            timeout=20,                 # llm_client will clamp by profile internally
            base_url="",                # resolved in ensure_loaded()
            model_url="",
            model_name_hint="",
            max_tokens=int(max_new_tokens),
            with_grammar_auto=False
        )
    except Exception as e:
        raise RuntimeError(f"gen failed: {e}")
    # Best-effort cleanup of any meta markers
    try:
        text = LC._strip_meta_markers(text)
    except Exception:
        pass
    return (text or "").strip()

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
        return ""  # chatbot disabled

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

    try:
        prompt = _build_chat_prompt(sys_prompt, msgs)
        answer = _generate_llm(prompt, reply_budget)
        if not answer:
            return "LLM error: empty reply"
    except Exception as e:
        return f"LLM error: {e}"

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
    app = FastAPI(title="Jarvis Prime – Chat Lane (Clean)")

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

        try:
            prompt = _build_chat_prompt(sys_prompt, msgs)
            answer = _generate_llm(prompt, reply_budget)
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

                msgs = MEM.trim_by_tokens(
                    chat_id=chat_id,
                    new_user=user_msg,
                    sys_prompt=sys_prompt,
                    max_total_tokens=max_total,
                    reply_budget=reply_budget,
                )

                try:
                    prompt = _build_chat_prompt(sys_prompt, msgs)
                    answer = _generate_llm(prompt, reply_budget)
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

if __name__ == "__main__" and _FASTAPI_OK:
    import uvicorn
    uvicorn.run("chatbot:app", host="0.0.0.0", port=8189, reload=False)