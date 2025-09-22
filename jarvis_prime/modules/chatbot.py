#!/usr/bin/env python3
# /app/chat.py
#
# Jarvis Prime — Chat + Web (explicit) helper
# - Default: offline chat via llm_client.chat_generate (pure chat, no persona banners)
# - Explicit web mode: only when the prompt clearly asks to search/browse the internet
#   (keywords like: search, look up, lookup, web, internet, online, browse/browsing, news, latest, updates, breaking)
# - Summarizes web snippets into a short paragraph, then lists sources
# - Falls back to offline LLM when search fails or times out

from __future__ import annotations

import os
import re
import json
import time
import html
import traceback
from typing import Dict, List, Tuple, Optional

# ============================
# LLM bridge
# ============================
try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _llm_ready() -> bool:
    return _LLM is not None and hasattr(_LLM, "chat_generate")

def _chat_offline_singleturn(user_msg: str, max_new_tokens: int = 256) -> str:
    """
    Minimal 1-turn chat: defers system prompt to llm_client (uses /app/system_prompt.txt if present).
    """
    if not _llm_ready():
        return ""
    try:
        return _LLM.chat_generate(
            messages=[{"role":"user","content":user_msg}],
            system_prompt="",
            max_new_tokens=max_new_tokens
        ) or ""
    except Exception:
        return ""

def _chat_offline_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    """
    Ask the local LLM to synthesize a concise answer from web notes/snippets.
    """
    if not _llm_ready():
        return ""
    sys_prompt = (
        "You are a concise synthesizer. Using only the provided bullet notes, write a clear 4–6 sentence answer. "
        "Prefer concrete facts & dates. Do not include URLs in the body. If info is conflicting, note it briefly."
    )
    msgs = [
        {"role":"system","content":sys_prompt},
        {"role":"user","content":f"Question: {question.strip()}\n\nNotes:\n{notes.strip()}\n\nWrite the answer now."}
    ]
    try:
        return _LLM.chat_generate(messages=msgs, system_prompt="", max_new_tokens=max_new_tokens) or ""
    except Exception:
        return ""

# Shared cleaners from llm_client if available
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

def _clean_text(s: str) -> str:
    if not s:
        return s
    out = s.replace("\r", "").strip()
    if _strip_trans:
        out = _strip_trans(out)
    if _scrub_pers:
        out = _scrub_pers(out)
    if _scrub_meta:
        out = _scrub_meta(out)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()

# ============================
# Web triggers (explicit)
# ============================
_WEB_TRIGGERS = [
    r"\bsearch\b",
    r"\blook\s*up\b",
    r"\blookup\b",
    r"\b(on\s+the\s+)?web\b",
    r"\binternet\b",
    r"\bonline\b",
    r"\bbrowse|browsing\b",
    r"\bnews\b",
    r"\blatest\b",
    r"\bupdates?\b",
    r"\bbreaking\b",
]

def _should_use_web(q: str) -> bool:
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

# ============================
# DuckDuckGo search (best-effort)
# 1) Try duckduckgo_search library if available
# 2) Fallback to DuckDuckGo Instant Answer API
# ============================
def _search_with_duckduckgo_lib(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception:
        return []
    try:
        out: List[Dict[str, str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                # r fields often: title, href, body
                title = (r.get("title") or "").strip()
                url = (r.get("href") or "").strip()
                snippet = (r.get("body") or "").strip()
                if title and url:
                    out.append({"title": title, "url": url, "snippet": snippet})
        return out
    except Exception:
        return []

def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 8) -> List[Dict[str, str]]:
    import requests
    try:
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "0",
        }
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    results: List[Dict[str, str]] = []

    def _push(title: str, url: str, snippet: str):
        title = (title or "").strip()
        url = (url or "").strip()
        snippet = (snippet or "").strip()
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})

    # Primary abstract
    abs_text = data.get("AbstractText") or ""
    abs_url = data.get("AbstractURL") or ""
    abs_src = data.get("AbstractSource") or ""
    if abs_text and abs_url:
        _push(f"{abs_src}: {abs_text[:60]}…" if abs_src else "DuckDuckGo Abstract", abs_url, abs_text)

    # Results
    for it in (data.get("Results") or []):
        _push(it.get("Text") or it.get("FirstURL") or "", it.get("FirstURL") or "", it.get("Text") or "")

    # Related topics may be nested
    for it in (data.get("RelatedTopics") or []):
        if "Topics" in it and isinstance(it["Topics"], list):
            for t in it["Topics"]:
                _push(t.get("Text") or t.get("FirstURL") or "", t.get("FirstURL") or "", t.get("Text") or "")
        else:
            _push(it.get("Text") or it.get("FirstURL") or "", it.get("FirstURL") or "", it.get("Text") or "")

    # Dedup and cap
    seen = set()
    deduped: List[Dict[str,str]] = []
    for r in results:
        key = r["url"]
        if key and key not in seen:
            seen.add(key)
            deduped.append(r)
        if len(deduped) >= max_results:
            break
    return deduped

def _duckduckgo_search(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    hits = _search_with_duckduckgo_lib(query, max_results=max_results)
    if hits:
        return hits
    return _search_with_ddg_api(query, max_results=max_results)

# ============================
# Web answer renderer
# ============================
def _render_web_answer(summary: str, sources: List[Tuple[str, str]]) -> str:
    lines: List[str] = []
    if summary.strip():
        lines.append(summary.strip())
    if sources:
        lines.append("\nSources:")
        for title, url in sources[:5]:
            # Avoid ultra-long URLs making the card messy
            t = title.strip() or url.strip()
            lines.append(f"• {t} — {url}")
    return "\n".join(lines).strip()

def _build_notes_from_hits(hits: List[Dict[str,str]]) -> str:
    notes = []
    for h in hits[:6]:
        t = html.unescape((h.get("title") or "").strip())
        s = html.unescape((h.get("snippet") or "").strip())
        u = (h.get("url") or "").strip()
        if t or s:
            note = f"- {t} — {s}".strip(" —")
            # keep URL out of the note body (we show URLs in Sources)
            notes.append(note)
    return "\n".join(notes)

# ============================
# Public API (used by bot.py)
# ============================
def handle_chat_command(kind: str) -> Tuple[str, None]:
    """
    Lightweight commands used by bot.py (e.g., jokes).
    Returns (message, None)
    """
    k = (kind or "").strip().lower()
    if k in ("joke", "pun", "laugh"):
        prompt = "Tell me a short, clean, original joke. One or two sentences."
        ans = _chat_offline_singleturn(prompt, max_new_tokens=140)
        if not ans.strip():
            ans = "Knock, knock. Who’s there? Cache. Cache who? Bless you."
        return (_clean_text(ans), None)

    # fallback: treat as offline chat
    ans = _chat_offline_singleturn(kind, max_new_tokens=256)
    return (_clean_text(ans) or "(no reply)", None)

def handle(user_text: str) -> str:
    """
    Natural entry point you can call from anywhere:
    - Uses explicit triggers to decide web vs offline
    - Web path: search → synthesize → render summary + sources
    - Offline path: pure chat
    """
    q = (user_text or "").strip()
    if not q:
        return ""

    # Decide path
    if _should_use_web(q):
        try:
            hits = _duckduckgo_search(q, max_results=6)
        except Exception:
            hits = []

        if hits:
            notes = _build_notes_from_hits(hits)
            # Try to synthesize with LLM; if that fails, use the best snippet/title
            summary = _chat_offline_summarize(q, notes, max_new_tokens=320).strip()
            if not summary:
                # crude fallback: first snippet/title stitched
                h0 = hits[0]
                t0 = (h0.get("title") or "").strip()
                s0 = (h0.get("snippet") or "").strip()
                summary = (s0 or t0 or "Here are some sources I found.")
            sources = [(h.get("title") or h.get("url") or "").strip(), (h.get("url") or "").strip()] for h in hits
            sources = [(t, u) for (t, u) in sources if u]
            return _render_web_answer(_clean_text(summary), sources)

        # No hits → graceful fallback offline (mark as offline answer)
        offline = _chat_offline_singleturn(q, max_new_tokens=240)
        return (_clean_text(offline) + "\n\n(offline answer)") if offline.strip() else "(no reply)"

    # Offline default
    ans = _chat_offline_singleturn(q, max_new_tokens=256)
    return _clean_text(ans) or "(no reply)"

# Convenience alias used by older callers
def chat(text: str) -> str:
    return handle(text)

# ============================
# CLI quick test
# ============================
if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "search latest SpaceX Starship update"
    print(handle(ask))