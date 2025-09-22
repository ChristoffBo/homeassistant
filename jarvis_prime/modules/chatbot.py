#!/usr/bin/env python3
# /app/chat.py
#
# Jarvis Prime — Chat + Web (explicit) helper
# - Default: offline chat via llm_client.chat_generate (pure chat, no persona banners)
# - Explicit web mode: only when the prompt clearly asks to search/browse the internet
#   (keywords like: search the web, internet search, web search, google it, look up on the web, etc.)
# - If the offline LLM answers with empty / "I don't know", auto-escalate to web mode
# - Web fallback ladder: DDG lib → DDG IA API → Wikipedia → Wikidata → offline fallback
# - Summarizes web snippets into a short paragraph, then lists sources
# - Never raises; always returns a string

from __future__ import annotations

import re
import html
import json
import time
from typing import Dict, List, Tuple, Optional

# ============================
# LLM bridge
# ============================
try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _log(msg: str):
    # lightweight debug log; safe in HA add-on logs
    print(f"[chat] {msg}", flush=True)

def _llm_ready() -> bool:
    return _LLM is not None and hasattr(_LLM, "chat_generate")

def _chat_offline_singleturn(user_msg: str, max_new_tokens: int = 256) -> str:
    """
    Minimal 1-turn chat: defers system prompt to llm_client (uses /app/system_prompt.txt if present).
    Never raises.
    """
    if not _llm_ready():
        _log("offline chat skipped: llm_client not ready")
        return ""
    try:
        out = _LLM.chat_generate(
            messages=[{"role":"user","content":user_msg}],
            system_prompt="",
            max_new_tokens=max_new_tokens
        ) or ""
        return out.strip()
    except Exception as e:
        _log(f"offline chat error: {e}")
        return ""

def _chat_offline_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    """
    Ask the local LLM to synthesize a concise answer from web notes/snippets.
    Never raises; empty string on failure.
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
        return (_LLM.chat_generate(messages=msgs, system_prompt="", max_new_tokens=max_new_tokens) or "").strip()
    except Exception as e:
        _log(f"summarize error: {e}")
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
# Web triggers (explicit) + unknown detector
# ============================
# Explicit triggers ONLY:
_WEB_TRIGGERS = [
    r"\bsearch\s+the\s+web\b",
    r"\bweb\s+search\b",
    r"\binternet\s+search\b",
    r"\bsearch\s+online\b",
    r"\bgoogle\s+it\b",
    r"\blook\s*up\s+on\s+the\s+web\b",
    r"\bsearch\s+the\s+internet\b",
]

def _should_use_web(q: str) -> bool:
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

_UNKNOWN_PATTERNS = [
    r"\bi\s+don'?t\s+know\b",
    r"\bnot\s+sure\b",
    r"\bi'?m\s+not\s+sure\b",
    r"\bno\s+idea\b",
    r"\bunknown\b",
    r"\bi\s+can'?t\s+answer\b",
    r"\bi\s+can'?t\s+find\b",
    r"\bI\s+don'?t\s+have\s+that\b",
]

def _looks_unknown(ans: str) -> bool:
    a = (ans or "").strip().lower()
    if not a:
        return True
    if len(a) < 6:
        return True
    return any(re.search(rx, a, re.I) for rx in _UNKNOWN_PATTERNS)

# ============================
# HTTP helper
# ============================
def _http_get_json(url: str, params: Optional[dict] = None, timeout: int = 5) -> Optional[dict]:
    try:
        import requests
    except Exception:
        _log("requests not available; cannot web search")
        return None
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        _log(f"http get json failed: {e}")
        return None

# ============================
# DuckDuckGo search
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
                title = (r.get("title") or "").strip()
                url = (r.get("href") or "").strip()
                snippet = (r.get("body") or "").strip()
                if title and url:
                    out.append({"title": title, "url": url, "snippet": snippet})
        return out
    except Exception as e:
        _log(f"DDGS lib search failed: {e}")
        return []

def _search_with_ddg_api(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    data = _http_get_json(
        "https://api.duckduckgo.com/",
        params={
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "0",
        },
        timeout=5,
    )
    if not data:
        return []
    results: List[Dict[str, str]] = []

    def _push(title: str, url: str, snippet: str):
        title = (title or "").strip()
        url = (url or "").strip()
        snippet = (snippet or "").strip()
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})

    abs_text = data.get("AbstractText") or ""
    abs_url = data.get("AbstractURL") or ""
    abs_src = data.get("AbstractSource") or ""
    if abs_text and abs_url:
        _push(f"{abs_src}: {abs_text[:60]}…" if abs_src else "DuckDuckGo Abstract", abs_url, abs_text)

    for it in (data.get("Results") or []):
        _push(it.get("Text") or it.get("FirstURL") or "", it.get("FirstURL") or "", it.get("Text") or "")

    for it in (data.get("RelatedTopics") or []):
        if isinstance(it, dict) and "Topics" in it and isinstance(it["Topics"], list):
            for t in it["Topics"]:
                _push(t.get("Text") or t.get("FirstURL") or "", t.get("FirstURL") or "", t.get("Text") or "")
        else:
            _push(it.get("Text") or it.get("FirstURL") or "", it.get("FirstURL") or "", it.get("Text") or "")

    # Dedup + cap
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
        _log(f"DDG lib hits: {len(hits)}")
        return hits
    hits = _search_with_ddg_api(query, max_results=max_results)
    if hits:
        _log(f"DDG IA hits: {len(hits)}")
    return hits

# ============================
# Wikipedia & Wikidata fallbacks
# ============================
def _wikipedia_hits(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    # Opensearch → Summary for first few
    opensearch = _http_get_json(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "opensearch", "search": query, "limit": max_results, "namespace": 0, "format": "json"},
        timeout=5,
    )
    if not opensearch or not isinstance(opensearch, list) or len(opensearch) < 4:
        return []
    titles = opensearch[1] or []
    descs  = opensearch[2] or []
    urls   = opensearch[3] or []
    hits: List[Dict[str, str]] = []
    for i, title in enumerate(titles[:max_results]):
        url = (urls[i] if i < len(urls) else "") or ""
        desc = (descs[i] if i < len(descs) else "") or ""
        title = (title or "").strip()
        url = (url or "").strip()
        desc = (desc or "").strip()
        if not title:
            continue
        # Try summary (rest_v1)
        summary_data = _http_get_json(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
            params={"redirect": "true"},
            timeout=5,
        )
        snippet = desc
        if summary_data and isinstance(summary_data, dict):
            extr = (summary_data.get("extract") or "").strip()
            if extr:
                snippet = extr
            if not url:
                url = (summary_data.get("content_urls", {}).get("desktop", {}).get("page", "") or "").strip()
        if title and (url or snippet):
            hits.append({"title": title, "url": url, "snippet": snippet})
    _log(f"Wikipedia hits: {len(hits)}")
    return hits

def _wikidata_hits(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    data = _http_get_json(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbsearchentities",
            "search": query,
            "language": "en",
            "format": "json",
            "limit": max_results,
        },
        timeout=5,
    )
    if not data or "search" not in data:
        return []
    out: List[Dict[str, str]] = []
    for ent in data.get("search", [])[:max_results]:
        title = (ent.get("label") or ent.get("description") or "").strip()
        url = ("https://www.wikidata.org/wiki/" + ent.get("id", "")).strip()
        snippet = (ent.get("description") or "").strip()
        if title and url:
            out.append({"title": title, "url": url, "snippet": snippet})
    _log(f"Wikidata hits: {len(out)}")
    return out

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
            t = (title or url).strip()
            lines.append(f"• {t} — {url}")
    return "\n".join(lines).strip()

def _build_notes_from_hits(hits: List[Dict[str,str]]) -> str:
    notes = []
    for h in hits[:6]:
        t = html.unescape((h.get("title") or "").strip())
        s = html.unescape((h.get("snippet") or "").strip())
        if t or s:
            note = f"- {t} — {s}".strip(" —")
            notes.append(note)
    return "\n".join(notes)

def _summarize_from_hits(question: str, hits: List[Dict[str, str]]) -> str:
    notes = _build_notes_from_hits(hits)
    if notes.strip():
        summary = _chat_offline_summarize(question, notes, max_new_tokens=320).strip()
        if summary:
            return summary
    # crude backup if LLM summarizer unavailable
    h0 = hits[0]
    t0 = (h0.get("title") or "").strip()
    s0 = (h0.get("snippet") or "").strip()
    return (s0 or t0 or "Here are some sources I found.").strip()

# ============================
# Public API (used by bot.py)
# ============================
def handle_chat_command(kind: str) -> Tuple[str, None]:
    """
    Lightweight commands used by bot.py (e.g., jokes).
    Returns (message, None)
    Never raises.
    """
    try:
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
    except Exception as e:
        _log(f"handle_chat_command error: {e}")
        return "(no reply)", None

def _web_fallback_chain(q: str) -> str:
    """
    Try the chain: DDG lib → DDG IA → Wikipedia → Wikidata.
    Returns rendered answer (summary + sources) or "".
    """
    try:
        # 1) DDG lib / IA
        hits = _duckduckgo_search(q, max_results=6)
        if not hits:
            # 2) Wikipedia
            hits = _wikipedia_hits(q, max_results=5)
        if not hits:
            # 3) Wikidata
            hits = _wikidata_hits(q, max_results=5)

        if hits:
            summary = _summarize_from_hits(q, hits)
            sources = [((h.get("title") or h.get("url") or "").strip(), (h.get("url") or "").strip()) for h in hits]
            sources = [(t, u) for (t, u) in sources if u]
            return _render_web_answer(_clean_text(summary), sources)
        return ""
    except Exception as e:
        _log(f"web fallback chain error: {e}")
        return ""

def handle(user_text: str) -> str:
    """
    Natural entry point you can call from anywhere:
    - OFFLINE by default
    - Web path ONLY when explicitly asked via trigger keywords
    - If offline result is empty/unknown, escalate to web
    - Never raises
    """
    q = (user_text or "").strip()
    if not q:
        return ""

    try:
        # 1) Explicit web mode?
        if _should_use_web(q):
            web_ans = _web_fallback_chain(q)
            if web_ans:
                return web_ans
            # If web fails, fall back to offline
            offline = _chat_offline_singleturn(q, max_new_tokens=240)
            return _clean_text(offline) or "I don’t know."

        # 2) Offline default
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        ans_clean = _clean_text(ans)

        # 3) If empty or “don’t know”, escalate to web
        if _looks_unknown(ans_clean):
            web_ans = _web_fallback_chain(q)
            if web_ans:
                return web_ans
            # still nothing → be honest
            return "I don’t know."

        return ans_clean or "I don’t know."
    except Exception as e:
        _log(f"handle fatal error: {e}")
        try:
            # last-resort: pure offline try
            fallback = _chat_offline_singleturn(q, max_new_tokens=240)
            return _clean_text(fallback) or "I don’t know."
        except Exception:
            return "I don’t know."

# Convenience alias (legacy callers)
def chat(text: str) -> str:
    return handle(text)

# ============================
# CLI quick test
# ============================
if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "search the web latest SpaceX Starship static fire"
    print(handle(ask))