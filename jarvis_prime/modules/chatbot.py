#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat only, no internet backends)
# - Default: offline Jarvis LLM chat via llm_client.chat_generate
# - If HA RAG facts exist, summarize them
# - Otherwise fall back to offline LLM directly
# - No Wikipedia, DDG, Reddit, or other external calls

import os, re, traceback
from typing import Dict

# ----------------------------
# Config / globals
# ----------------------------
DEBUG = bool(os.environ.get("JARVIS_DEBUG"))
_CACHE: Dict[str,str] = {}

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
    """General fallback: send user query directly to the LLM."""
    if not _llm_ready():
        return ""
    try:
        return _LLM.chat_generate(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt=(
                "You are Jarvis, a helpful and factual assistant. "
                "Answer clearly with general knowledge when possible. "
                "If you truly cannot answer, say 'I don't know'."
            ),
            max_new_tokens=max_new_tokens,
        ) or ""
    except Exception:
        return ""

def _chat_offline_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    """Summarizer mode: when HA RAG provides notes, synthesize them into an answer."""
    if not _llm_ready():
        return ""
    sys_prompt = (
        "You are Jarvis, a concise synthesizer. Using only the provided bullet notes, "
        "write a clear 4–6 sentence answer. Prefer concrete facts & dates. Avoid speculation. "
        "If info is conflicting, note it briefly."
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
# Public entry
# ----------------------------
def handle_message(source: str, text: str) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    try:
        if DEBUG: print("IN_MSG:", q)

        # 1) Try RAG context first (local HA facts)
        try:
            from rag import inject_context
            try:
                rag_block = inject_context(q, top_k=5)
            except Exception:
                rag_block = ""
            if rag_block:
                ans = _chat_offline_summarize(q, rag_block, max_new_tokens=256)
                clean_ans = _clean_text(ans)
                if clean_ans:
                    if DEBUG: print("RAG_HIT")
                    return clean_ans
        except Exception:
            pass

        # 2) Cache
        if q in _CACHE:
            if DEBUG: print("CACHE_HIT")
            return _CACHE[q]

        # 3) General offline LLM fallback
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        clean_ans = _clean_text(ans)
        if clean_ans:
            _CACHE[q] = clean_ans
            return clean_ans

        # 4) Final fallback
        return "I don't know."

    except Exception:
        if DEBUG:
            traceback.print_exc()
        return "I don't know."

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
        try:
            out = _strip_trans(out)
        except Exception:
            pass
    if _scrub_pers:
        try:
            out = _scrub_pers(out)
        except Exception:
            pass
    if _scrub_meta:
        try:
            out = _scrub_meta(out)
        except Exception:
            pass
    return re.sub(r"\n{3,}","\n\n",out).strip()

if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "Who is Tom Cruise"
    print(handle_message("cli", ask))