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
# - Fallbacks: summarizer fallback + direct snippet mode for fact queries
# - Integrations: DuckDuckGo (ddgs), Wikipedia API, Reddit (vetted), GitHub (tech)
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

def _min_hits_for_query(q: str) -> int:
    core = [w for w in _tokenize(q) if w not in {"where","what","who","when","which","the","and","for","with","from","into","about","this","that"}]
    if "f1" in core or "formula" in core or "leader" in core:
        return 1
    return 1 if len(core) <= 2 else 2

def _strip_web_triggers(q: str) -> str:
    out = q
    for pat in [
        r"\bgoogle\s+it\b", r"\bgoogle\s+for\s+me\b", r"\bgoogle\b",
        r"\bsearch\s+the\s+internet\b", r"\bsearch\s+the\s+web\b",
        r"\bweb\s+search\b", r"\binternet\s+search\b",
        r"\bcheck\s+internet\b", r"\bcheck\s+web\b",
        r"\bcheck\s+online\b", r"\bsearch\s+online\b",
        r"\blook\s+it\s+up\b", r"\buse\s+the\s+internet\b",
        r"\bverify\s+online\b", r"\bverify\s+on\s+the\s+web\b",
    ]:
        out = re.sub(pat, "", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip(" .!?-")
    return out
def _is_junk_result(title: str, snippet: str, url: str, q: str, vertical: str) -> bool:
    if not title and not snippet:
        return True
    if _is_deny_domain(url):
        return True
    text = (title or "") + " " + (snippet or "")
    if not _is_english_text(text, max_ratio=0.2):
        return True
    min_hits = _min_hits_for_query(q)
    if not _keyword_overlap(q, title, snippet, min_hits=min_hits):
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
    return [h for _, h in scored]

_WEB_TRIGGERS = [
    r"\bgoogle\s+it\b", r"\bgoogle\s+for\s+me\b", r"\bgoogle\b",
    r"\bsearch\s+the\s+internet\b", r"\bsearch\s+the\s+web\b",
    r"\bweb\s+search\b", r"\binternet\s+search\b",
    r"\bcheck\s+internet\b", r"\bcheck\s+web\b",
    r"\bcheck\s+online\b", r"\bsearch\s+online\b",
    r"\blook\s+it\s+up\b", r"\buse\s+the\s+internet\b",
    r"\bverify\s+online\b", r"\bverify\s+on\s+the\s+web\b",
]

def _should_use_web(q: str) -> bool:
    return any(re.search(p, (q or ""), re.I) for p in _WEB_TRIGGERS)

def _cb_fail(backend: str):
    CIRCUIT_BREAKERS[backend] = time.time()

def _cb_open(backend: str) -> bool:
    return backend in CIRCUIT_BREAKERS and (time.time() - CIRCUIT_BREAKERS[backend]) < CB_TIMEOUT

# ----------------------------
# Web search backends
# ----------------------------
def _search_with_duckduckgo_lib(query: str, max_results: int = 6, region: str = "us-en") -> List[Dict[str,str]]:
    if _cb_open("ddg_lib"): return []
    try:
        from ddgs import DDGS
    except Exception:
        return []
    try:
        out = []
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

def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 6) -> List[Dict[str,str]]:
    if _cb_open("ddg_api"): return []
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1", "skip_disambig": "0", "kl": "us-en"}
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        _cb_fail("ddg_api")
        return []
    results = []
    def _push(title, url, snippet):
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
    if data.get("AbstractText") and data.get("AbstractURL"):
        _push(data.get("AbstractSource") or "DuckDuckGo", data.get("AbstractURL"), data.get("AbstractText"))
    for it in (data.get("Results") or []):
        _push(it.get("Text") or "", it.get("FirstURL") or "", it.get("Text") or "")
    for it in (data.get("RelatedTopics") or []):
        if "Topics" in it:
            for t in it["Topics"]:
                _push(t.get("Text") or "", t.get("FirstURL") or "", t.get("Text") or "")
        else:
            _push(it.get("Text") or "", it.get("FirstURL") or "", it.get("Text") or "")
    seen, deduped = set(), []
    for r in results:
        u = r.get("url") or ""
        if u and u not in seen:
            seen.add(u)
            deduped.append(r)
        if len(deduped) >= max_results:
            break
    return deduped

def _search_with_wikipedia(query: str, timeout: int = 6) -> List[Dict[str,str]]:
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

def _search_with_reddit(query: str, max_results: int = 4, timeout: int = 6) -> List[Dict[str,str]]:
    try:
        url = f"https://www.reddit.com/search.json?q={_urlquote(query)}&sort=relevance&t=month&limit={max_results}"
        r = requests.get(url, headers={"User-Agent": "JarvisBot/1.0"}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        hits = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            sub = d.get("subreddit", "").lower()
            title = d.get("title") or ""
            snippet = d.get("selftext") or d.get("title") or ""
            link = "https://www.reddit.com" + d.get("permalink", "")
            if title and link:
                hits.append({"title": f"r/{sub}: {title}", "url": link, "snippet": snippet})
        return hits
    except Exception:
        return []
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
    if len(hits) >= max_results:
        return hits
    hits.extend(_search_with_ddg_api(shaped_q, max_results=max_results))
    if len(hits) >= max_results:
        return hits
    # Last fallback: Reddit
    hits.extend(_search_with_reddit(raw_q, max_results=max_results))
    return hits[:max_results]

def _web_search(query: str, max_results: int = 8) -> List[Dict[str,str]]:
    vertical = _detect_intent(query)
    shaped = _build_query_by_vertical(query, vertical)
    hits = _try_all_backoffs(query, shaped, vertical, max_results)
    ranked = _rank_hits(query, hits, vertical)
    return ranked[:max_results] if ranked else []

def _build_notes_from_hits(hits: List[Dict[str,str]]) -> str:
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

def _render_web_answer(summary: str, sources: List[Tuple[str,str]]) -> str:
    lines: List[str] = []
    if summary.strip():
        lines.append(summary.strip())
    if sources:
        dedup, seen = [], set()
        for title, url in sources:
            if not url or url in seen or _is_deny_domain(url):
                continue
            seen.add(url)
            dedup.append((title, url))
        if dedup:
            lines.append("\nSources:")
            for title, url in dedup[:5]:
                lines.append(f"• {title.strip() or _domain_of(url)} — {url.strip()}")
    return "\n".join(lines).strip()

_CACHE: Dict[str,str] = {}
_LAST_QUERY: Optional[str] = None

def handle_message(source: str, text: str) -> str:
    global _LAST_QUERY
    q = (text or "").strip()
    if not q:
        return ""
    try:
        if q in _CACHE:
            return _CACHE[q]

        is_trigger = _should_use_web(q)
        stripped = _strip_web_triggers(q)

        if is_trigger:
            real_q = stripped if stripped else (_LAST_QUERY or q)
            if not real_q:
                return "No results found."
            hits = _web_search(real_q, max_results=8)
            if hits:
                notes = _build_notes_from_hits(hits)
                summary = _chat_offline_summarize(real_q, notes, max_new_tokens=320).strip()
                if not summary:
                    h0 = hits[0]
                    summary = h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources = [(h.get("title") or h.get("url") or "", h.get("url") or "") for h in hits if h.get("url")]
                out = _render_web_answer(_clean_text(summary), sources)
                _CACHE[real_q] = out
                _LAST_QUERY = real_q
                return out
            _LAST_QUERY = real_q
            return "No results found."

        real_q = stripped if stripped else q
        _LAST_QUERY = real_q

        try:
            from rag import inject_context
            rag_block = ""
            try:
                rag_block = inject_context(real_q, top_k=5)
            except Exception:
                pass
            if rag_block:
                ans = _chat_offline_summarize(real_q, rag_block, max_new_tokens=256)
                clean_ans = _clean_text(ans)
                if clean_ans:
                    _CACHE[real_q] = clean_ans
                    return clean_ans
        except Exception:
            pass

        ans = _chat_offline_singleturn(real_q, max_new_tokens=256)
        clean_ans = _clean_text(ans)
        if clean_ans:
            _CACHE[real_q] = clean_ans
            return clean_ans

        return "I don't know."

    except Exception:
        return "I don't know."

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

if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "Who is the current F1 leader Google it"
    print(handle_message("cli", ask))