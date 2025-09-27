#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat only, no internet backends)
# - Default: offline Jarvis LLM chat via llm_client.chat_generate
# - If HA RAG facts exist, summarize them
# - Otherwise fall back to offline LLM directly

import os, re, traceback
from typing import Dict, Optional
import time

# ----------------------------
# Config / globals
# ----------------------------
DEBUG = bool(os.environ.get("JARVIS_DEBUG"))
_CACHE: Dict[str,str] = {}
_CACHE_TTL = 3600  # 1 hour cache TTL
_CACHE_TIMESTAMPS: Dict[str,float] = {}

# ----------------------------
# Query classification
# ----------------------------
def _classify_query(text: str) -> str:
    """Classify query type to help routing decisions"""
    tokens = set(re.findall(r"[A-Za-z0-9_]+", text.lower()))
    
    # Home automation keywords
    ha_keywords = {
        "battery", "soc", "solar", "light", "switch", "sensor", "temperature", 
        "humidity", "motion", "door", "window", "home", "away", "where",
        "axpert", "inverter", "grid", "load", "power", "energy", "pv"
    }
    
    # Entertainment/general knowledge keywords  
    entertainment_keywords = {
        "actor", "actress", "movie", "film", "tv", "show", "series", "celebrity",
        "who is", "what is", "tell me about", "explain"
    }
    
    if tokens & ha_keywords:
        return "homeautomation"
    elif any(phrase in text.lower() for phrase in ["who is", "what is", "tell me about"]):
        return "general"
    elif tokens & entertainment_keywords:
        return "general"
    else:
        return "unknown"

def _should_use_rag(query: str, query_type: str) -> bool:
    """Determine if RAG should be used for this query"""
    # Only use RAG for home automation queries
    if query_type == "homeautomation":
        return True
    
    # Skip RAG for general knowledge questions
    if query_type == "general":
        return False
        
    # For unknown queries, check for specific HA-related terms
    ha_terms = {"battery", "soc", "solar", "light", "switch", "temperature", "where", "home"}
    tokens = set(re.findall(r"[A-Za-z0-9_]+", query.lower()))
    return bool(tokens & ha_terms)

# ----------------------------
# Cache management
# ----------------------------
def _is_cache_valid(key: str) -> bool:
    """Check if cached entry is still valid"""
    if key not in _CACHE_TIMESTAMPS:
        return False
    return (time.time() - _CACHE_TIMESTAMPS[key]) < _CACHE_TTL

def _get_from_cache(key: str) -> Optional[str]:
    """Get from cache if valid"""
    if key in _CACHE and _is_cache_valid(key):
        return _CACHE[key]
    elif key in _CACHE:
        # Remove expired cache entry
        del _CACHE[key]
        del _CACHE_TIMESTAMPS[key]
    return None

def _store_in_cache(key: str, value: str) -> None:
    """Store in cache with timestamp"""
    _CACHE[key] = value
    _CACHE_TIMESTAMPS[key] = time.time()

# ----------------------------
# LLM bridge (Jarvis)
# ----------------------------
try:
    import llm_client as _LLM
except ImportError:
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
    except Exception as e:
        if DEBUG: print(f"[CHAT] LLM singleturn failed: {e}")
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
    except Exception as e:
        if DEBUG: print(f"[CHAT] LLM summarize failed: {e}")
        return ""

# ----------------------------
# RAG integration
# ----------------------------
def _try_rag_context(query: str) -> Optional[str]:
    """Try to get RAG context, with proper error handling"""
    try:
        from rag import inject_context
        rag_block = inject_context(query, top_k=8)
        if rag_block and rag_block.strip():
            if DEBUG: print(f"[CHAT] RAG context: {len(rag_block)} chars")
            return rag_block
        else:
            if DEBUG: print("[CHAT] RAG returned empty context")
            return None
    except ImportError:
        if DEBUG: print("[CHAT] RAG module not available")
        return None
    except Exception as e:
        if DEBUG: print(f"[CHAT] RAG failed: {e}")
        return None

# ----------------------------
# Public entry
# ----------------------------
def handle_message(source: str, text: str) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    
    try:
        if DEBUG: print(f"[CHAT] IN_MSG: {q}")

        # Classify the query
        query_type = _classify_query(q)
        if DEBUG: print(f"[CHAT] Query type: {query_type}")

        # Check cache first
        cached_answer = _get_from_cache(q)
        if cached_answer:
            if DEBUG: print("[CHAT] CACHE_HIT")
            return cached_answer

        # Try RAG context if appropriate
        if _should_use_rag(q, query_type):
            rag_block = _try_rag_context(q)
            if rag_block:
                ans = _chat_offline_summarize(q, rag_block, max_new_tokens=256)
                clean_ans = _clean_text(ans)
                if clean_ans:
                    _store_in_cache(q, clean_ans)
                    if DEBUG: print("[CHAT] RAG_HIT")
                    return clean_ans
                else:
                    if DEBUG: print("[CHAT] RAG summarization failed")
        else:
            if DEBUG: print("[CHAT] Skipping RAG for this query type")

        # General offline LLM fallback
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        clean_ans = _clean_text(ans)
        if clean_ans:
            _store_in_cache(q, clean_ans)
            if DEBUG: print("[CHAT] LLM_FALLBACK")
            return clean_ans

        # Final fallback
        if DEBUG: print("[CHAT] NO_ANSWER")
        return "I don't know."

    except Exception as e:
        if DEBUG:
            print(f"[CHAT] Exception: {e}")
            traceback.print_exc()
        return "I don't know."

# ----------------------------
# Text cleaning
# ----------------------------
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

def _clean_text(s: str) -> str:
    if not s:
        return s
    out = s.replace("\r","").strip()
    
    # Apply cleaning functions if available
    cleaners = [_strip_trans, _scrub_pers, _scrub_meta]
    for cleaner in cleaners:
        if cleaner:
            try:
                out = cleaner(out)
            except Exception:
                continue
    
    # Normalize whitespace
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out

# ----------------------------
# Utility functions
# ----------------------------
def get_cache_stats() -> Dict[str, int]:
    """Get cache statistics for debugging"""
    valid_entries = sum(1 for key in _CACHE if _is_cache_valid(key))
    return {
        "total_entries": len(_CACHE),
        "valid_entries": valid_entries,
        "expired_entries": len(_CACHE) - valid_entries
    }

def clear_cache() -> None:
    """Clear all cache entries"""
    global _CACHE, _CACHE_TIMESTAMPS
    _CACHE.clear()
    _CACHE_TIMESTAMPS.clear()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        print("Cache stats:", get_cache_stats())
    elif len(sys.argv) > 1 and sys.argv[1] == "clear":
        clear_cache()
        print("Cache cleared")
    else:
        ask = " ".join(sys.argv[1:]).strip() or "Who is Tom Cruise"
        print(handle_message("cli", ask))
