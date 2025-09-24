#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web fallback)
# - Default: offline Jarvis LLM chat via llm_client.chat_generate
# - Web mode only if wake words are present ("google it", "search the web", etc.)
# - Topic aware routing:
#     * entertainment: IMDb/Wikipedia/RT/Metacritic (Reddit only vetted movie subs, not for fact queries)
#     * tech/dev: GitHub + StackExchange + Reddit tech subs
#     * sports: F1/ESPN/FIFA official; Reddit excluded for fact queries
#     * general: Wikipedia/Britannica/Biography/History
# - Filters: English-only, block junk/low-signal domains, require keyword overlap
# - Ranking: authority + keyword overlap + strong recency for facts
# - Integrations: DuckDuckGo, Wikipedia
# - Free, no-register APIs only

import os, re, json, time, html, requests, datetime, traceback, threading
from typing import Dict, List, Tuple, Optional
from urllib.parse import quote as _urlquote
from functools import lru_cache

# ----------------------------
# Config / globals
# ----------------------------
DEBUG = bool(os.environ.get("JARVIS_DEBUG"))
CIRCUIT_BREAKERS: Dict[str, float] = {}
CB_TIMEOUT = 120  # seconds to mute a backend after repeated failure

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
        "If info is conflicting, note it briefly. Rank recent and authoritative sources higher."
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
# Topic detection
# ----------------------------
_TECH_KEYS = re.compile(
    r"\b(api|bug|error|exception|stacktrace|repo|github|docker|k8s|kubernetes|linux|debian|ubuntu|arch|kernel|python|node|golang|go|java|c\+\+|rust|mysql|postgres|sql|ssh|tls|ssl|dns|vpn|proxmox|homeassistant|zimaos|opnsense)\b",
    re.I,
)
_ENT_KEYS  = re.compile(
    r"\b(movie|film|actor|actress|imdb|rotten|metacritic|trailer|box office|release|cast|director)\b",
    re.I,
)
_SPORT_KEYS = re.compile(
    r"\b(f1|formula 1|grand prix|premier league|nba|nfl|fifa|world cup|uefa|olympics|tennis|atp|wta|golf|pga)\b",
    re.I,
)

def _detect_intent(q: str) -> str:
    ql = (q or "").lower()
    if _TECH_KEYS.search(ql):
        return "tech"
    if _SPORT_KEYS.search(ql):
        return "sports"
    if _ENT_KEYS.search(ql) or re.search(r"\b(last|latest)\b.*\b(movie|film)\b", ql):
        return "entertainment"
    if re.search(r"\b(movie|film)\b", ql):
        return "entertainment"
    return "general"

# ----------------------------
# Helpers & filters
# ----------------------------
_AUTHORITY_COMMON = [
    "wikipedia.org", "britannica.com", "biography.com", "history.com"
]
_AUTHORITY_ENT = [
    "imdb.com", "rottentomatoes.com", "metacritic.com", "boxofficemojo.com"
]
_AUTHORITY_SPORTS = [
    "espn.com", "fifa.com", "nba.com", "nfl.com", "olympics.com", "formula1.com",
    "autosport.com", "motorsport.com", "the-race.com"
]
_AUTHORITY_TECH = [
    "github.com", "gitlab.com", "stackoverflow.com", "superuser.com", "serverfault.com",
    "unix.stackexchange.com", "askubuntu.com", "archlinux.org", "kernel.org",
    "docs.python.org", "nodejs.org", "golang.org",
    "learn.microsoft.com", "answers.microsoft.com", "support.microsoft.com",
    "man7.org", "linux.org"
]

_DENY_DOMAINS = [
    "zhihu.com","baidu.com","pinterest.","quora.com","tumblr.com",
    "vk.com","weibo.","4chan","8kun","/forum","forum.","boards.",
    "linktr.ee","tiktok.com","facebook.com","notebooklm.google.com"
]

def _tokenize(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2]

def _keyword_overlap(q: str, title: str, snippet: str, min_hits: int = 2) -> bool:
    qk = set(_tokenize(q))
    tk = set(_tokenize((title or "") + " " + (snippet or "")))
    stop = {"where","what","who","when","which","the","and","for","with","from","into",
            "about","this","that","your","you","are","was","were","have","has","had",
            "movie","film","films","videos","watch","code","codes","list","sale","sell","selling"}
    qk = {w for w in qk if w not in stop}
    return len(qk & tk) >= min_hits

def _domain_of(url: str) -> str:
    try:
        return re.sub(r"^www\.", "", re.findall(r"https?://([^/]+)/?", url, re.I)[0].lower())
    except Exception:
        return ""

def _is_deny_domain(url: str) -> bool:
    d = _domain_of(url)
    test = d + url.lower()
    return any(bad in test for bad in _DENY_DOMAINS)

def _is_authority(url: str, vertical: str) -> bool:
    d = _domain_of(url)
    pool = set(_AUTHORITY_COMMON)
    if vertical == "entertainment":
        pool.update(_AUTHORITY_ENT)
    elif vertical == "sports":
        pool.update(_AUTHORITY_SPORTS)
    elif vertical == "tech":
        pool.update(_AUTHORITY_TECH)
    return any(d.endswith(ad) for ad in pool)

# Fact-style queries
_FACT_QUERY_RE = re.compile(r"\b(last|latest|when|date|year|who|winner|won|result|release|final|most recent|current leader)\b", re.I)
_CURRENT_YEAR = datetime.datetime.utcnow().year

def _rank_hits(q: str, hits: List[Dict[str,str]], vertical: str) -> List[Dict[str,str]]:
    scored = []
    facty = bool(_FACT_QUERY_RE.search(q))
    for h in hits:
        url = (h.get("url") or "")
        title = (h.get("title") or "")
        snip = (h.get("snippet") or "")
        if not url:
            continue
        if _is_deny_domain(url):
            continue
        score = 0
        if _is_authority(url, vertical):
            score += 8 if facty else 6
        overlap_bonus = len(set(_tokenize(q)) & set(_tokenize(title + " " + snip)))
        score += min(overlap_bonus, 4)
        years = re.findall(r"\b(20[0-9]{2})\b", title + " " + snip)
        if years:
            newest = max(int(y) for y in years)
            if newest >= _CURRENT_YEAR:
                score += 6
        scored.append((score, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored]
# ----------------------------
# Triggers (force web only if present)
# ----------------------------
_WEB_TRIGGERS = [
    r"\bgoogle\s+it\b", r"\bgoogle\s+for\s+me\b", r"\bgoogle\b",
    r"\bsearch\s+the\s+internet\b", r"\bsearch\s+the\s+web\b",
    r"\bweb\s+search\b", r"\binternet\s+search\b",
]

def _should_use_web(q: str) -> bool:
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

# ----------------------------
# Circuit breaker helpers
# ----------------------------
def _cb_fail(backend: str):
    CIRCUIT_BREAKERS[backend] = time.time()

def _cb_open(backend: str) -> bool:
    if backend not in CIRCUIT_BREAKERS:
        return False
    return (time.time() - CIRCUIT_BREAKERS[backend]) < CB_TIMEOUT

# ----------------------------
# Web search backends
# ----------------------------
def _search_with_duckduckgo_lib(query: str, max_results: int = 6, region: str = "us-en") -> List[Dict[str,str]]:
    if _cb_open("ddg_lib"): return []
    try:
        from duckduckgo_search import DDGS
    except Exception:
        return []
    try:
        out: List[Dict[str,str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, region=region, safesearch="Moderate"):
                out.append({
                    "title": (r.get("title") or "").strip(),
                    "url": (r.get("href") or "").strip(),
                    "snippet": (r.get("body") or "").strip(),
                })
        return out
    except Exception:
        _cb_fail("ddg_lib")
        return []

def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 6) -> List[Dict[str,str]]:
    if _cb_open("ddg_api"): return []
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1", "skip_disambig": "0", "kl": "us-en"}
        r = requests.get(url, params=params, timeout=timeout)
        data = r.json()
    except Exception:
        _cb_fail("ddg_api")
        return []
    results: List[Dict[str,str]] = []
    if data.get("AbstractText") and data.get("AbstractURL"):
        results.append({"title": data.get("AbstractSource") or "", "url": data.get("AbstractURL"), "snippet": data.get("AbstractText")})
    for it in (data.get("Results") or []):
        results.append({"title": it.get("Text") or "", "url": it.get("FirstURL") or "", "snippet": it.get("Text") or ""})
    return results[:max_results]

def _search_with_wikipedia(query: str, timeout: int = 6) -> List[Dict[str,str]]:
    try:
        api = "https://en.wikipedia.org/api/rest_v1/page/summary/" + _urlquote(query)
        r = requests.get(api, timeout=timeout, headers={"accept": "application/json"})
        if r.status_code == 200:
            data = r.json()
            return [{
                "title": data.get("title") or "",
                "url": data.get("content_urls", {}).get("desktop", {}).get("page") or "",
                "snippet": data.get("extract") or ""
            }]
    except Exception:
        return []
    return []

# ----------------------------
# Query shaping + backoffs
# ----------------------------
def _build_query_by_vertical(q: str, vertical: str) -> str:
    if vertical == "entertainment":
        return f"{q} site:imdb.com OR site:wikipedia.org"
    if vertical == "sports":
        return f"{q} site:espn.com OR site:formula1.com OR site:wikipedia.org"
    if vertical == "tech":
        return f"{q} site:github.com OR site:stackoverflow.com OR site:wikipedia.org"
    return q + " site:wikipedia.org"

def _try_all_backoffs(raw_q: str, shaped_q: str, vertical: str, max_results: int) -> List[Dict[str,str]]:
    hits: List[Dict[str,str]] = []
    hits.extend(_search_with_wikipedia(raw_q))
    if len(hits) >= max_results:
        return hits
    hits.extend(_search_with_duckduckgo_lib(shaped_q, max_results=max_results))
    if len(hits) >= max_results:
        return hits
    hits.extend(_search_with_ddg_api(shaped_q, max_results=max_results))
    return hits[:max_results]

# ----------------------------
# Web search orchestration
# ----------------------------
def _web_search(query: str, max_results: int = 8) -> List[Dict[str,str]]:
    vertical = _detect_intent(query)
    shaped = _build_query_by_vertical(query, vertical)
    hits = _try_all_backoffs(query, shaped, vertical, max_results)
    return _rank_hits(query, hits, vertical)[:max_results]

# ----------------------------
# Notes builder
# ----------------------------
def _build_notes_from_hits(hits: List[Dict[str,str]]) -> str:
    lines = []
    for h in hits:
        dom = _domain_of(h.get("url",""))
        title = h.get("title") or "(no title)"
        snippet = (h.get("snippet") or "")[:400]
        url = h.get("url") or ""
        lines.append(f"- [{dom}] {title} :: {snippet} :: {url}")
    return "\n".join(lines) if lines else "- No usable notes"

# ----------------------------
# Render
# ----------------------------
def _render_web_answer(summary: str, sources: List[Tuple[str,str]]) -> str:
    lines: List[str] = []
    if summary.strip():
        lines.append(summary.strip())
    if sources:
        lines.append("\nSources:")
        seen = set()
        for title, url in sources:
            if not url or url in seen or _is_deny_domain(url):
                continue
            seen.add(url)
            lines.append(f"• {title.strip() or _domain_of(url)} — {url.strip()}")
    return "\n".join(lines).strip()
# ----------------------------
# Public entry
# ----------------------------
_CACHE: Dict[str,str] = {}

def handle_message(source: str, text: str) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    try:
        if DEBUG: print("IN_MSG:", q)

        # 1) Explicit trigger → force web search, skip offline
        if _should_use_web(q):
            hits = _web_search(q, max_results=8)
            if hits:
                notes = _build_notes_from_hits(hits)
                summary = _chat_offline_summarize(q, notes, max_new_tokens=320).strip()
                if not summary:
                    h0 = hits[0]
                    summary = h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources = [(h.get("title") or h.get("url") or "", h.get("url") or "") for h in hits if h.get("url")]
                return _render_web_answer(_clean_text(summary), sources)
            return "I don't know."

        # 2) Otherwise → RAG first
        try:
            from rag import inject_context
            rag_block = inject_context(q, top_k=5)
        except Exception:
            rag_block = ""
        if rag_block:
            ans = _chat_offline_summarize(q, rag_block, max_new_tokens=256)
            clean_ans = _clean_text(ans)
            if clean_ans:
                return clean_ans

        # 3) Offline Jarvis
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        return _clean_text(ans) or "I don't know."

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
        try: out = _strip_trans(out)
        except Exception: pass
    if _scrub_pers:
        try: out = _scrub_pers(out