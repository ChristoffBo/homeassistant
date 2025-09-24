#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web fallback)
# - Default: offline Jarvis LLM chat via llm_client.chat_generate
# - Web mode if wake words are present OR offline LLM fails OR offline text says "cannot search / please verify / unsure"
# - Topic aware routing:
#     * entertainment: IMDb/Wikipedia/RT/Metacritic (Reddit only vetted movie subs, not for fact queries)
#     * tech/dev: GitHub + StackExchange + Reddit tech subs
#     * sports: F1/ESPN/FIFA official; Reddit excluded for fact queries
#     * general: Wikipedia/Britannica/Biography/History
# - Filters: English-only, block junk/low-signal domains, require keyword overlap
# - Ranking: authority + keyword overlap + strong recency for facts
# - Fallbacks: summarizer fallback + direct snippet mode for fact queries
# - Integrations: DuckDuckGo (ddgs), Wikipedia API, Reddit (vetted), GitHub (tech)
# - Free, no-register APIs only
# - Human behavior heuristics: prefer clear facts, recency, multiple perspectives, avoid spammy/repetitive sources

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
MAX_PARALLEL_TIMEOUT = 3

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

_REDDIT_ALLOW_ENT = {"movies","TrueFilm","MovieDetails","tipofmytongue","criterion","oscarrace"}
_REDDIT_ALLOW_TECH = {"learnpython","python","programming","sysadmin","devops","linux","selfhosted","homelab","docker","kubernetes","opensource","techsupport","homeassistant","homeautomation"}

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

def _is_english_text(text: str, max_ratio: float = 0.2) -> bool:
    if not text:
        return True
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return (non_ascii / max(1, len(text))) <= max_ratio

def _is_junk_result(title: str, snippet: str, url: str, q: str, vertical: str) -> bool:
    if not title and not snippet:
        return True
    if _is_deny_domain(url):
        return True
    text = (title or "") + " " + (snippet or "")
    if not _is_english_text(text, max_ratio=0.2):
        return True
    if not _keyword_overlap(q, title, snippet, min_hits=1):
        return True
    if re.search(r"\b(price|venmo|cashapp|zelle|paypal|gift\s*card|promo\s*code|digital\s*code|[$][0-9])\b", text, re.I):
        return True
    if "reddit.com" in url.lower():
        m = re.search(r"/r/([A-Za-z0-9_]+)/", url)
        sub = (m.group(1).lower() if m else "")
        if vertical == "entertainment":
            if sub not in {s.lower() for s in _REDDIT_ALLOW_ENT}:
                return True
        elif vertical == "tech":
            if sub not in {s.lower() for s in _REDDIT_ALLOW_TECH}:
                return True
        elif vertical == "sports":
            if sub not in {"formula1","motorsports"}:
                return True
    return False

# Fact-style queries (used by ranker)
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
        if _is_junk_result(title, snip, url, q, vertical):
            continue
        score = 0
        if _is_authority(url, vertical):
            score += 8 if facty else 6
        u = url.lower()
        if vertical == "tech" and ("github.com" in u or "stackoverflow.com" in u):
            score += 3
        if vertical == "entertainment" and ("imdb.com" in u or "rottentomatoes.com" in u or "metacritic.com" in u):
            score += 5 if facty else 3
        if vertical == "sports" and ("formula1.com" in u or "espn.com" in u):
            score += 5 if facty else 3
        score += min(len(snip)//120, 3)
        overlap_bonus = len(set(_tokenize(q)) & set(_tokenize(title + " " + snip)))
        score += min(overlap_bonus, 4)
        years = re.findall(r"\b(20[0-9]{2})\b", (title or "") + " " + (snip or ""))
        if years:
            newest = max(int(y) for y in years)
            if newest >= _CURRENT_YEAR:
                score += 6 if facty else 4
            elif newest == _CURRENT_YEAR - 1:
                score += 4 if facty else 2
            elif newest < _CURRENT_YEAR - 5:
                score -= 3
        scored.append((score, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [h for _, h in scored]
    return ranked

# ----------------------------
# Triggers
# ----------------------------
_WEB_TRIGGERS = [
    r"\bgoogle\s+it\b[.!?]?", r"\bgoogle\s+for\s+me\b[.!?]?", r"\bgoogle\b[.!?]?",
    r"\bsearch\s+the\s+internet\b[.!?]?", r"\bsearch\s+the\s+web\b[.!?]?",
    r"\bweb\s+search\b[.!?]?", r"\binternet\s+search\b[.!?]?",
    r"\bcheck\s+internet\b[.!?]?", r"\bcheck\s+web\b[.!?]?",
    r"\bcheck\s+online\b[.!?]?", r"\bsearch\s+online\b[.!?]?",
    r"\blook\s+it\s+up\b[.!?]?", r"\buse\s+the\s+internet\b[.!?]?",
    r"\bverify\s+online\b[.!?]?", r"\bverify\s+on\s+the\s+web\b[.!?]?",
]

def _should_use_web(q: str) -> bool:
    ql = (q or "").lower()
    for p in _WEB_TRIGGERS:
        if re.search(p, ql, re.I):
            return True
    return False

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
def _search_with_duckduckgo_lib(query: str, max_results: int = 6, region: str = "us-en") -> List[Dict[str, str]]:
    if _cb_open("ddg_lib"): return []
    try:
        from duckduckgo_search import DDGS
    except Exception:
        return []
    try:
        out: List[Dict[str, str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, region=region, safesearch="Moderate"):
                title = (r.get("title") or "").strip()
                url = (r.get("href") or "").strip()
                snippet = (r.get("body") or "").strip()
                if title and url:
                    out.append({"title": title, "url": url, "snippet": snippet})
        return out
    except Exception:
        _cb_fail("ddg_lib")
        return []

def _search_with_wikipedia(query: str, timeout: int = 6) -> List[Dict[str, str]]:
    try:
        api = "https://en.wikipedia.org/api/rest_v1/page/summary/" + _urlquote(query)
        r = requests.get(api, timeout=timeout, headers={"accept": "application/json"})
        if r.status_code == 200:
            data = r.json()
            title = data.get("title") or ""
            desc = data.get("extract") or ""
            url = data.get("content_urls", {}).get("desktop", {}).get("page") or ""
            if title and url and desc:
                return [{"title": title, "url": url, "snippet": desc}]
    except Exception:
        return []
    return []
# ----------------------------
# Query shaping + backoffs
# ----------------------------
def _build_query_by_vertical(q: str, vertical: str) -> str:
    q = q.strip()
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
    return hits[:max_results]

# ----------------------------
# Web search orchestration
# ----------------------------
def _web_search(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    vertical = _detect_intent(query)
    shaped = _build_query_by_vertical(query, vertical)
    hits = _try_all_backoffs(query, shaped, vertical, max_results)
    ranked = _rank_hits(query, hits, vertical)
    return ranked[:max_results] if ranked else []

# ----------------------------
# Notes builder
# ----------------------------
def _build_notes_from_hits(hits: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for h in hits[:10]:
        title = (h.get("title") or "").strip()
        url   = (h.get("url") or "").strip()
        snip  = (h.get("snippet") or "").strip()
        dom   = _domain_of(url)
        if title or snip:
            lines.append(f"- [{dom}] {title if title else '(no title)'} :: {snip[:500]} :: {url}")
    if not lines:
        return "- No usable web notes."
    return "\n".join(lines)

# ----------------------------
# Render
# ----------------------------
def _render_web_answer(summary: str, sources: List[Tuple[str, str]]) -> str:
    lines: