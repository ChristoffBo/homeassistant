#!/usr/bin/env python3

import os, re, traceback
from typing import Dict

DEBUG = bool(os.environ.get("JARVIS_DEBUG"))
_CACHE: Dict[str, str] = {}

# ----------------------------
# LLM bridge (Jarvis)
# ----------------------------
try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _llm_ready() -> bool:
    return _LLM is not None and hasattr(_LLM, "chat_generate")

def _chat_offline_singleturn(user_msg: str, max_new_tokens: int = 256) -> str:
    if not _llm_ready():
        return ""
    try:
        return _LLM.chat_generate(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=(
                "You are Jarvis, a helpful and factual assistant. "
                "Answer clearly if you know. If you truly cannot answer, say 'I don't know'."
            ),
            max_new_tokens=max_new_tokens,
        ) or ""
    except Exception:
        return ""

def _chat_offline_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    if not _llm_ready():
        return ""
    sys_prompt = (
        "You are Jarvis, a concise synthesizer. Using only the provided bullet notes, "
        "write a clear 4–6 sentence answer. Prefer concrete facts & dates. Avoid speculation. "
        "If info is conflicting, note it briefly. Rank recent and authoritative notes higher."
    )
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Question: {question.strip()}\n\nNotes:\n{notes.strip()}\n\nWrite the answer now."},
    ]
    try:
        return _LLM.chat_generate(messages=msgs, system_prompt="", max_new_tokens=max_new_tokens) or ""
    except Exception:
        return ""

# ----------------------------
# RAG helpers
# ----------------------------
def _try_rag_context(q: str) -> str:
    try:
        from rag import inject_context
        rag_block = inject_context(q, top_k=5)
    except Exception:
        rag_block = ""
    if rag_block:
        ans = _chat_offline_summarize(q, rag_block, max_new_tokens=256)
        return _clean_text(ans)
    return ""

# ----------------------------
# Cleaners
# ----------------------------
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

def _clean_text(s: str) -> str:
    if not s:
        return s
    out = s.replace("\r","").strip()
    if _strip_trans:
        try: out = _strip_trans(out)
        except Exception: pass
    if _scrub_pers:
        try: out = _scrub_pers(out)
        except Exception: pass
    if _scrub_meta:
        try: out = _scrub_meta(out)
        except Exception: pass
    return re.sub(r"\n{3,}","\n\n",out).strip()

# ----------------------------
# Public entry
# ----------------------------
def handle_message(source: str, text: str) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    try:
        if DEBUG: print("IN_MSG:", q)

        # 1) Try RAG context
        rag_ans = _try_rag_context(q)
        if rag_ans:
            return rag_ans

        # 2) Cache
        if q in _CACHE:
            if DEBUG: print("CACHE_HIT")
            return _CACHE[q]

        # 3) Offline Jarvis
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        clean_ans = _clean_text(ans)

        # 4) Save to cache and return if valid
        if clean_ans and clean_ans.lower() not in {
            "i don't know.","i dont know","unknown","no idea","i'm not sure","i am unsure"
        }:
            _CACHE[q] = clean_ans
            return clean_ans

        # 5) Final fallback
        return "I don't know."

    except Exception:
        if DEBUG:
            traceback.print_exc()
        return "I don't know."

if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "Hello Jarvis"
    print(handle_message("cli", ask))