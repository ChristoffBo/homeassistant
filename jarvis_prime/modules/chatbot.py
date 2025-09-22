#!/usr/bin/env python3
# /app/chat.py
#
# Jarvis Prime — Hybrid Chat (offline + web-on-demand)
# - Natural chat via llm_client.chat_generate()
# - If user text implies web intent (“search / web / internet / latest / news ...”),
#   run a fast DuckDuckGo HTML search (no API key), skim top result, and
#   feed concise context to the LLM. Append a tiny "Sources:" footer.
# - If the web is slow/unavailable, gracefully fall back to offline chat.
#
# Public entry:
#   handle_chat_command(message: str) -> tuple[str, dict]
#     • If message == "joke" → quick LLM joke (for bot.py compatibility)
#     • Else → normal chat with auto web intent detection
#
# Notes:
# - Tight timeouts to keep chat snappy.
# - Small in-memory cache with TTL to avoid repeat fetches.
# - Pure stdlib HTTP; respectful headers; no dependencies.
# - Keeps the illusion: one cohesive answer, sources footer is minimal.
#
# You can tweak the TRIGGERS / TIMEOUTS / LIMITS near the top.

from __future__ import annotations
import os
import re
import time
import html
import json
import urllib.parse
import urllib.request
import urllib.error
import socket
from typing import Dict, List, Tuple, Optional
from collections import deque

# ============================
# Config knobs
# ============================
# Web-intent trigger words (lower-case); tuned to feel natural, not noisy
_WEB_TRIGGERS = (
    r"\bsearch\b",
    r"\blook\s*up\b",
    r"\b(on\s+the\s+)?web\b",
    r"\b(on\s+the\s+)?internet\b",
    r"\bnews\b",
    r"\blatest\b",
    r"\bwho\s+is\b",
    r"\bwhat\s+is\b",
    r"\bwhen\s+(did|was)\b",
    r"\bhow\s+to\b",
    r"\brelease\s+date\b",
    r"\breleased\b",
)

# We only flip to "web mode" if at least one trigger is present
_WEB_INTENT_RX = re.compile("|".join(_WEB_TRIGGERS), re.I)

# DuckDuckGo HTML endpoint
_DDG_HTML = "https://duckduckgo.com/html/?q={q}&kl=us-en"

# Networking timeouts
HTTP_TIMEOUT_S = 4.0         # per HTTP request (search & skim)
MAX_FETCH_SIZE = 1_000_000   # cap skim downloads (~1 MB)

# Parsing & prompt limits
MAX_RESULTS = 5              # take top N DDG results
MAX_SOURCES = 4              # show at most N sources in footer
SKIM_CHARS = 1600            # max chars from skimmed page
CTX_SNIPPET_CHARS = 900      # max chars of search snippets fed to LLM
LLM_REPLY_TOKENS = 280       # generation tokens for web answers (kept tight)

# Cache settings
CACHE_TTL_S = 600            # 10 minutes
_CACHE: Dict[str, Tuple[float, List[Dict[str, str]]]] = {}
_SKIM_CACHE: Dict[str, Tuple[float, str]] = {}

# ============================
# LLM glue
# ============================
try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _llm_ok() -> bool:
    return (_LLM is not None) and hasattr(_LLM, "chat_generate")

def _llm_chat(messages: List[Dict[str, str]], max_tokens: int) -> str:
    # system_prompt="" → llm_client will load /app/system_prompt.txt if present
    return _LLM.chat_generate(messages=messages, system_prompt="", max_new_tokens=max_tokens) if _llm_ok() else ""

# Helpers reused from llm_client if present (for cleanup)
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

def _clean_text(s: str) -> str:
    if not s:
        return s
    out = s
    if _strip_trans:
        out = _strip_trans(out)
    if _scrub_pers:
        out = _scrub_pers(out)
    if _scrub_meta:
        out = _scrub_meta(out)
    out = re.sub(r'\n{3,}', '\n\n', out or "").strip()
    return out

# ============================
# Web intent detection
# ============================
def _detect_web_intent(user_text: str) -> bool:
    if not user_text:
        return False
    # don’t trigger on obvious local/admin terms
    local_rx = re.compile(r"\b(radarr|sonarr|kuma|technitium|dns|arr|qnap|unraid|docker|home\s*assistant)\b", re.I)
    if local_rx.search(user_text or ""):
        return False
    return bool(_WEB_INTENT_RX.search(user_text or ""))

def _extract_query(user_text: str) -> str:
    # basic heuristic: remove wakewords "chat" / "talk" at start, then strip filler
    s = (user_text or "").strip()
    for kw in ("chat", "talk"):
        if s.lower().startswith(kw):
            s = s[len(kw):].strip(" :,-")
            break
    # remove leading verbs like "search", "look up"
    s = re.sub(r"^(search|look\s*up)\s*", "", s, flags=re.I)
    return s or user_text

# ============================
# DuckDuckGo HTML search (no API)
# ============================
def _http_get(url: str, timeout: float = HTTP_TIMEOUT_S, max_bytes: Optional[int] = None) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (JarvisPrime; +https://example.invalid)",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(MAX_FETCH_SIZE if max_bytes is None else min(MAX_FETCH_SIZE, max_bytes))
        return data

_DDG_RESULT_RX = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet[^>]*>(.*?)</a?>',
    re.I | re.S
)

def _decode_ddg_link(href: str) -> str:
    # /l/?kh=-1&uddg=<encoded>
    try:
        if "uddg=" in href:
            q = urllib.parse.urlparse(href).query
            qs = urllib.parse.parse_qs(q)
            if "uddg" in qs:
                return urllib.parse.unquote(qs["uddg"][0])
        return href
    except Exception:
        return href

def _strip_html(s: str) -> str:
    # minimal HTML to text
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = re.sub(r"<\s*script[^>]*>.*?</\s*script\s*>", "", s, flags=re.I|re.S)
    s = re.sub(r"<\s*style[^>]*>.*?</\s*style\s*>", "", s, flags=re.I|re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def _ddg_search(query: str) -> List[Dict[str, str]]:
    q = urllib.parse.quote_plus(query.strip())
    url = _DDG_HTML.format(q=q)
    try:
        raw = _http_get(url, timeout=HTTP_TIMEOUT_S)
    except Exception:
        return []
    html_txt = raw.decode("utf-8", errors="ignore")
    out: List[Dict[str, str]] = []
    for m in _DDG_RESULT_RX.finditer(html_txt):
        href = html.unescape(m.group(1) or "").strip()
        title_html = m.group(2) or ""
        snippet_html = m.group(3) or ""
        url_clean = _decode_ddg_link(href)
        if not url_clean.startswith("http"):
            continue
        title = _strip_html(title_html)
        snippet = _strip_html(snippet_html)
        if not title:
            continue
        out.append({"title": title[:160], "url": url_clean, "snippet": snippet[:300]})
        if len(out) >= MAX_RESULTS:
            break
    return out

# ============================
# Skim top result
# ============================
def _skim(url: str) -> str:
    # cache
    now = time.time()
    hit = _SKIM_CACHE.get(url)
    if hit and (now - hit[0]) < CACHE_TTL_S:
        return hit[1]

    try:
        raw = _http_get(url, timeout=HTTP_TIMEOUT_S, max_bytes=MAX_FETCH_SIZE)
        text = _strip_html(raw.decode("utf-8", errors="ignore"))
        # simple paragraph-ish extraction: first 2–3 sentences
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = text[:SKIM_CHARS].strip()
    except Exception:
        text = ""

    _SKIM_CACHE[url] = (now, text)
    return text

# ============================
# Cache for search results
# ============================
def _cache_get(q: str) -> Optional[List[Dict[str, str]]]:
    now = time.time()
    hit = _CACHE.get(q.lower().strip())
    if hit and (now - hit[0]) < CACHE_TTL_S:
        return hit[1]
    return None

def _cache_put(q: str, results: List[Dict[str, str]]):
    _CACHE[q.lower().strip()] = (time.time(), results)

# ============================
# Compose LLM prompts
# ============================
def _prompt_with_web(user_text: str, results: List[Dict[str, str]], skim_text: str) -> List[Dict[str, str]]:
    # Build a tiny context block that keeps token use down and helps factuality
    ctx_lines: List[str] = []
    for r in results[:MAX_RESULTS]:
        bit = f"- {r.get('title','').strip()}: {r.get('snippet','').strip()}"
        if len(bit) > 220:
            bit = bit[:220].rstrip() + "…"
        if bit.strip("- :"):
            ctx_lines.append(bit)
    ctx = "\n".join(ctx_lines)
    if len(ctx) > CTX_SNIPPET_CHARS:
        ctx = ctx[:CTX_SNIPPET_CHARS].rstrip() + "…"

    skim_block = f"\n\nTop result skim:\n{skim_text}" if skim_text else ""
    system = (
        "You are a concise assistant. Use the provided snippets to answer the user's question. "
        "Cite specific facts when helpful. If unsure or conflicting, say so briefly. "
        "Write a single cohesive answer; do not output a bibliography. Keep it clear."
    )

    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Question:\n{user_text}\n\nSnippets:\n{ctx}{skim_block}"},
    ]
    return msgs

def _make_sources_footer(results: List[Dict[str, str]]) -> str:
    items = []
    for r in results[:MAX_SOURCES]:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        if not (title and url):
            continue
        # shorten domain path
        try:
            p = urllib.parse.urlparse(url)
            host = p.netloc
            path = (p.path or "/")[:40]
            hostpath = f"{host}{path}" if host else url
        except Exception:
            hostpath = url
        items.append(f"• {title} — {hostpath}")
    return ("\n\nSources:\n" + "\n".join(items)) if items else ""

# ============================
# Offline chat path
# ============================
def _answer_offline(user_text: str) -> str:
    msgs = [{"role": "user", "content": user_text}]
    out = _llm_chat(msgs, max_tokens=LLM_REPLY_TOKENS) or ""
    return _clean_text(out)

# ============================
# Web-assisted chat path
# ============================
def _answer_with_web(user_text: str) -> str:
    q = _extract_query(user_text)
    results = _cache_get(q)
    if results is None:
        try:
            results = _ddg_search(q)
        except Exception:
            results = []
        _cache_put(q, results or [])

    # If search turns up nothing, bail to offline
    if not results:
        return _answer_offline(user_text)

    # Skim top result to increase accuracy without heavy tokens
    skim_text = ""
    try:
        top_url = results[0].get("url", "")
        if top_url:
            skim_text = _skim(top_url)
    except Exception:
        skim_text = ""

    msgs = _prompt_with_web(user_text, results, skim_text)
    out = _llm_chat(msgs, max_tokens=LLM_REPLY_TOKENS) or ""
    cleaned = _clean_text(out) or "(no reply)"

    # Append sourced footer (not fed into the LLM to avoid regurgitation)
    footer = _make_sources_footer(results)
    return (cleaned + footer).strip()

# ============================
# Public API for bot.py
# ============================
def handle_chat_command(message: str) -> Tuple[str, Optional[dict]]:
    """
    Entry for bot.py.
      - If message == "joke": quick LLM joke.
      - Else: hybrid chat. If user phrasing implies web → answer_with_web, else offline.
    Returns: (text, extras_dict_or_None)
    """
    msg = (message or "").strip()
    if not msg:
        return ("", None)

    # Simple “joke” path retained for backwards compatibility with bot.py
    if msg.lower() == "joke":
        joke_msgs = [
            {"role": "system", "content": "You are witty and brief. Tell a single clean one-liner joke."},
            {"role": "user", "content": "One joke, one line."},
        ]
        out = _llm_chat(joke_msgs, max_tokens=80) or ""
        return (_clean_text(out) or "No joke right now.", {"bypass_beautify": True})

    # Hybrid: offline by default, go online if intent is clear
    try:
        if _detect_web_intent(msg):
            text = _answer_with_web(msg)
        else:
            text = _answer_offline(msg)
    except Exception as e:
        # Any failure falls back to offline chat
        try:
            text = _answer_offline(msg)
            text = (text + "\n\n(brief note: live web lookup unavailable right now)").strip()
        except Exception:
            text = f"(chat error: {e})"

    return (text or "", None)

# ============================
# Self-test
# ============================
if __name__ == "__main__":
    tests = [
        "chat search when was Windows 11 released?",
        "chat who is Valentino Rossi?",
        "chat latest news on SpaceX Starship",
        "talk what is RAID 10 vs RAID 5?",
        "chat tell me a joke",
    ]
    for t in tests:
        print("\nQ:", t)
        ans, _ = handle_chat_command(t)
        print("A:", ans[:800], "…" if len(ans) > 800 else "")