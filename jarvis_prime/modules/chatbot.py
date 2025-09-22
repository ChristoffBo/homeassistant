#!/usr/bin/env python3
# /app/chat.py
#
# Jarvis Prime — Chat + Web helper
# - Offline first: uses llm_client.chat_generate
# - Explicit web triggers (search the web, google it, etc.) OR empty/I don’t know → web fallback
# - Web fallback chain: DuckDuckGo lib → DDG API → Wikipedia → Wikidata
# - Synthesizes web notes into a natural 4–6 sentence answer, adds sources at bottom
# - If all fails: "I don't know."

from __future__ import annotations

import re
import html
import requests
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

def _chat_offline(user_msg: str, max_new_tokens: int = 256) -> str:
    if not _llm_ready():
        return ""
    try:
        return _LLM.chat_generate(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt="",
            max_new_tokens=max_new_tokens
        ) or ""
    except Exception:
        return ""

def _chat_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    if not _llm_ready():
        return ""
    sys_prompt = (
        "You are a concise synthesizer. Using only the provided bullet notes, "
        "write a clear 4–6 sentence answer. Prefer concrete facts & dates. "
        "Do not include URLs in the body. If info is conflicting, note it briefly."
    )
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Question: {question.strip()}\n\nNotes:\n{notes.strip()}\n\nWrite the answer now."}
    ]
    try:
        return _LLM.chat_generate(messages=msgs, system_prompt="", max_new_tokens=max_new_tokens) or ""
    except Exception:
        return ""

# ============================
# Cleaners
# ============================
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
# Web triggers (explicit)
# ============================
_WEB_TRIGGERS = [
    r"\bweb\s+search\b",
    r"\bsearch\s+the\s+web\b",
    r"\binternet\s+search\b",
    r"\bsearch\s+the\s+internet\b",
    r"\bsearch\s+online\b",
    r"\bgoogle\b",
    r"\bgoogle\s+it\b",
]

def _explicit_web(q: str) -> bool:
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

def _looks_like_idk(ans: str) -> bool:
    if not ans or not ans.strip():
        return True
    low = ans.lower()
    return any(x in low for x in ["i don't know", "not sure", "(no reply)"])

# ============================
# Web fallback helpers
# ============================
def _search_with_duckduckgo_lib(query: str, max_results: int = 6, timeout: int = 5) -> List[Dict[str, str]]:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception:
        return []
    try:
        out: List[Dict[str, str]] = []
        with DDGS(timeout=timeout) as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                out.append({
                    "title": (r.get("title") or "").strip(),
                    "url": (r.get("href") or "").strip(),
                    "snippet": (r.get("body") or "").strip()
                })
        return [h for h in out if h["title"] and h["url"]]
    except Exception:
        return []

def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 5) -> List[Dict[str, str]]:
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    results: List[Dict[str, str]] = []
    if data.get("AbstractText") and data.get("AbstractURL"):
        results.append({"title": data.get("AbstractSource") or "DuckDuckGo", "url": data["AbstractURL"], "snippet": data["AbstractText"]})
    for it in (data.get("Results") or []):
        results.append({"title": it.get("Text") or "", "url": it.get("FirstURL") or "", "snippet": it.get("Text") or ""})
    out = []
    seen = set()
    for r in results:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
        if len(out) >= max_results:
            break
    return out

def _wiki_summary(query: str, timeout: int = 5) -> List[Dict[str, str]]:
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(query)}"
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if "extract" in data and data.get("content_urls", {}).get("desktop", {}).get("page"):
            return [{
                "title": data.get("title") or "Wikipedia",
                "url": data["content_urls"]["desktop"]["page"],
                "snippet": data.get("extract") or ""
            }]
    except Exception:
        return []
    return []

def _wikidata_lookup(query: str, timeout: int = 5) -> List[Dict[str, str]]:
    try:
        url = "https://www.wikidata.org/w/api.php"
        params = {"action": "wbsearchentities", "search": query, "language": "en", "format": "json"}
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        results: List[Dict[str, str]] = []
        for ent in data.get("search", []):
            results.append({
                "title": ent.get("label") or "Wikidata",
                "url": f"https://www.wikidata.org/wiki/{ent.get('id')}",
                "snippet": ent.get("description") or ""
            })
        return results[:3]
    except Exception:
        return []

def _web_search(query: str, max_results: int = 6) -> Tuple[str, List[Tuple[str, str]]]:
    # Try chain: DDG lib → DDG API → Wiki → Wikidata
    hits: List[Dict[str, str]] = []
    for func in (_search_with_duckduckgo_lib, _search_with_ddg_api, _wiki_summary, _wikidata_lookup):
        try:
            hits = func(query, max_results=max_results) if func != _wiki_summary else func(query)
        except Exception:
            hits = []
        if hits:
            break
    if not hits:
        return "", []
    # Build notes for LLM
    notes = []
    for h in hits:
        t = html.unescape((h.get("title") or "").strip())
        s = html.unescape((h.get("snippet") or "").strip())
        if t or s:
            notes.append(f"- {t} — {s}")
    notes_text = "\n".join(notes)
    summary = _chat_summarize(query, notes_text, max_new_tokens=320).strip()
    if not summary:
        summary = hits[0].get("snippet") or hits[0].get("title") or "Here are some sources I found."
    sources = [((h.get("title") or h.get("url") or "").strip(), (h.get("url") or "").strip()) for h in hits if h.get("url")]
    return summary, sources

def _render(summary: str, sources: List[Tuple[str, str]]) -> str:
    if not summary and not sources:
        return "I don't know."
    lines = [summary.strip()] if summary.strip() else []
    if sources:
        lines.append("\nSources:")
        for t, u in sources[:5]:
            lines.append(f"• {t} — {u}")
    return "\n".join(lines).strip()

# ============================
# Public API
# ============================
def handle(user_text: str) -> str:
    q = (user_text or "").strip()
    if not q:
        return ""
    try:
        # Explicit triggers → web
        if _explicit_web(q):
            summary, sources = _web_search(q)
            return _render(_clean_text(summary), sources) if summary or sources else "I don't know."
        # Offline first
        ans = _chat_offline(q, max_new_tokens=256)
        ans_clean = _clean_text(ans)
        if _looks_like_idk(ans_clean):
            summary, sources = _web_search(q)
            return _render(_clean_text(summary), sources) if summary or sources else "I don't know."
        return ans_clean
    except Exception:
        return "I don't know."

def chat(text: str) -> str:
    return handle(text)

# ============================
# CLI quick test
# ============================
if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "search the web SpaceX Starship latest"
    print(handle(ask))