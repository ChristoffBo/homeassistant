#!/usr/bin/env python3
# /app/chat.py
#
# Jarvis Prime — Chat + Web helper
# - Default: offline chat via llm_client.chat_generate (pure chat, no persona banners)
# - Web mode: only when the prompt clearly asks to search/browse the internet
#   (keywords like: google it, google for me, search the internet, web search, internet search, check internet, check web)
# - Summarizes web snippets into a short paragraph, then lists sources
# - Falls back to offline LLM when search fails
# - If both fail → "I don't know."

from __future__ import annotations

import re
import html
from typing import Dict, List, Tuple

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
    if not _llm_ready():
        return ""
    try:
        return _LLM.chat_generate(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt="",
            max_new_tokens=max_new_tokens,
        ) or ""
    except Exception:
        return ""

def _chat_offline_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    if not _llm_ready():
        return ""
    sys_prompt = (
        "You are a concise synthesizer. Using only the provided bullet notes, write a clear 4–6 sentence answer. "
        "Prefer concrete facts & dates. Do not include URLs in the body. If info is conflicting, note it briefly."
    )
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Question: {question.strip()}\n\nNotes:\n{notes.strip()}\n\nWrite the answer now."},
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
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()

# ============================
# Web triggers (explicit only)
# ============================
_WEB_TRIGGERS = [
    r"\bgoogle\s+it\b",
    r"\bgoogle\s+for\s+me\b",
    r"\bsearch\s+the\s+internet\b",
    r"\binternet\s+search\b",
    r"\bweb\s+search\b",
    r"\bcheck\s+internet\b",
    r"\bcheck\s+web\b",
]

def _should_use_web(q: str) -> bool:
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

# ============================
# DuckDuckGo search
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
                title = (r.get("title") or "").strip()
                url = (r.get("href") or "").strip()
                snippet = (r.get("body") or "").strip()
                if title and url:
                    out.append({"title": title, "url": url, "snippet": snippet})
        return out
    except Exception:
        return []

def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 5) -> List[Dict[str, str]]:
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

    if data.get("AbstractText") and data.get("AbstractURL"):
        _push("DuckDuckGo Abstract", data["AbstractURL"], data["AbstractText"])

    for it in (data.get("Results") or []):
        _push(it.get("Text") or "", it.get("FirstURL") or "", it.get("Text") or "")

    for it in (data.get("RelatedTopics") or []):
        if isinstance(it, dict):
            if "Topics" in it:
                for t in it["Topics"]:
                    _push(t.get("Text") or "", t.get("FirstURL") or "", t.get("Text") or "")
            else:
                _push(it.get("Text") or "", it.get("FirstURL") or "", it.get("Text") or "")

    seen = set()
    deduped = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
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
    lines = []
    if summary.strip():
        lines.append(summary.strip())
    if sources:
        lines.append("\nSources:")
        for title, url in sources[:5]:
            t = title.strip() or url.strip()
            lines.append(f"• {t} — {url}")
    return "\n".join(lines).strip()

def _build_notes_from_hits(hits: List[Dict[str, str]]) -> str:
    notes = []
    for h in hits[:6]:
        t = html.unescape((h.get("title") or "").strip())
        s = html.unescape((h.get("snippet") or "").strip())
        if t or s:
            notes.append(f"- {t} — {s}")
    return "\n".join(notes)

# ============================
# Main handler
# ============================
def handle(user_text: str) -> str:
    q = (user_text or "").strip()
    if not q:
        return ""

    try:
        if _should_use_web(q):
            hits = _duckduckgo_search(q, max_results=6)
            if hits:
                notes = _build_notes_from_hits(hits)
                summary = _chat_offline_summarize(q, notes, max_new_tokens=320).strip()
                if not summary:
                    h0 = hits[0]
                    summary = h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources = [((h.get("title") or h.get("url") or "").strip(), (h.get("url") or "").strip()) for h in hits if h.get("url")]
                return _render_web_answer(_clean_text(summary), sources)

            # fallback to offline LLM if search yields nothing
            offline = _chat_offline_singleturn(q, max_new_tokens=240)
            return _clean_text(offline) or "I don't know."

        # Default offline mode
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        return _clean_text(ans) or "I don't know."
    except Exception:
        fallback = _chat_offline_singleturn(q, max_new_tokens=240)
        return _clean_text(fallback) or "I don't know."

def chat(text: str) -> str:
    return handle(text)

# ============================
# CLI quick test
# ============================
if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "web search latest SpaceX Starship update"
    print(handle(ask))