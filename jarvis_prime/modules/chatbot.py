#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web + RAG fallback)
# - Default: offline LLM chat via llm_client.chat_generate
# - RAG-first: inject HA entity facts (temperature, location, battery, etc.)
# - Web mode if wake words are present OR offline LLM fails OR offline text says "cannot search / please verify / unsure"
# - Topic aware routing:
#     * entertainment: IMDb/Wikipedia/RT/Metacritic (Reddit only vetted movie subs, not for fact queries)
#     * tech/dev: GitHub + StackExchange + Reddit tech subs
#     * sports: F1/ESPN/FIFA official; Reddit excluded for fact queries
#     * general: Wikipedia/Britannica/Biography/History
# - Filters: English-only, block junk/low-signal domains, require keyword overlap
# - Ranking: authority + keyword overlap + strong recency for facts
# - Fallbacks: RAG → summarizer → web → offline → “I don’t know”
# - Integrations: DuckDuckGo, Wikipedia, Reddit (vetted), GitHub (tech)
# - Free, no-register APIs only

import os, re, json, time, html, requests, datetime, traceback, threading
from typing import Dict, List, Tuple, Optional
from urllib.parse import quote as _urlquote

DEBUG = bool(os.environ.get("JARVIS_DEBUG"))

# ----------------------------
# LLM bridge
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
            system_prompt="",
            max_new_tokens=max_new_tokens,
        ) or ""
    except Exception:
        return ""

def _chat_offline_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    if not _llm_ready():
        return ""
    sys_prompt = (
        "You are a concise synthesizer. Using only the provided bullet notes, "
        "write a clear 4–6 sentence answer. Prefer concrete facts & dates. "
        "Avoid speculation. Rank recent and authoritative sources higher. "
        "Always respond naturally, like a helpful assistant."
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
# RAG loader & resolver
# ----------------------------
_RAG_PATHS = ["/share/jarvis_prime/memory/rag_facts.json", "/data/rag_facts.json"]
_RAG_CACHE: Dict[str, Dict[str,str]] = {}
_RAG_MTIME = 0.0
_RAG_LOCK = threading.Lock()

def _load_rag() -> None:
    """Load rag_facts.json into memory (cached)."""
    global _RAG_CACHE, _RAG_MTIME
    try:
        for p in _RAG_PATHS:
            if os.path.exists(p):
                mtime = os.path.getmtime(p)
                if mtime <= _RAG_MTIME:
                    return
                with open(p, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    with _RAG_LOCK:
                        _RAG_CACHE = data
                        _RAG_MTIME = mtime
                        if DEBUG:
                            print(f"RAG_LOADED {len(_RAG_CACHE)} entities from {p}")
                return
    except Exception as e:
        if DEBUG:
            print("RAG_LOAD_ERR", repr(e))

def _rag_lookup(user_q: str, top_k: int = 6) -> List[Tuple[str,str]]:
    """Find relevant entity facts for a user query."""
    _load_rag()
    ql = (user_q or "").lower()
    results: List[Tuple[str,str]] = []

    # simple keyword routing
    if any(w in ql for w in ["temp","temperature","heat","hot","cold"]):
        for eid, obj in _RAG_CACHE.items():
            if obj.get("device_class") == "temperature":
                results.append((obj.get("friendly_name") or eid, f"{obj.get('state')} {obj.get('unit_of_measurement','')}"))
    if any(w in ql for w in ["where","location","zone","arrive","leave","home"]):
        for eid, obj in _RAG_CACHE.items():
            if eid.startswith("person.") or eid.startswith("zone."):
                results.append((obj.get("friendly_name") or eid, obj.get("state")))
    if any(w in ql for w in ["battery","soc","charge","percent"]):
        for eid, obj in _RAG_CACHE.items():
            if obj.get("device_class") == "battery":
                results.append((obj.get("friendly_name") or eid, f"{obj.get('state')} {obj.get('unit_of_measurement','%')}"))
    if any(w in ql for w in ["time","date","clock","now"]):
        for eid, obj in _RAG_CACHE.items():
            if "time" in eid or "date" in eid:
                results.append((obj.get("friendly_name") or eid, obj.get("state")))

    # fallback: fuzzy match against friendly names
    toks = set(re.findall(r"[a-z0-9]+", ql))
    for eid, obj in _RAG_CACHE.items():
        name = (obj.get("friendly_name") or eid).lower()
        if toks & set(name.split()):
            results.append((obj.get("friendly_name") or eid, obj.get("state")))

    # dedupe and cap
    seen, out = set(), []
    for t in results:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out[:top_k]

def _rag_block(user_q: str, top_k: int = 6, max_chars: int = 1024) -> str:
    facts = _rag_lookup(user_q, top_k=top_k)
    lines = [f"- {name}: {val}" for name,val in facts if name and val]
    block = "\n".join(lines)
    return block[:max_chars]
# ----------------------------
# Topic detection
# ----------------------------
_TECH_KEYS = re.compile(r"\b(api|bug|error|exception|stacktrace|repo|github|docker|k8s|kubernetes|linux|debian|ubuntu|arch|kernel|python|node|golang|go|java|c\+\+|rust|mysql|postgres|sql|ssh|tls|ssl|dns|vpn|proxmox|homeassistant|zimaos|opnsense)\b", re.I)
_ENT_KEYS  = re.compile(r"\b(movie|film|actor|actress|imdb|rotten|metacritic|trailer|box office|release|cast|director)\b", re.I)
_SPORT_KEYS = re.compile(r"\b(f1|formula 1|grand prix|premier league|nba|nfl|fifa|world cup|uefa|olympics|tennis|atp|wta|golf|pga)\b", re.I)

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
    if not _keyword_overlap(q, title, snippet, min_hits=2):
        return True
    # Kill commerce / resale / code-list spam
    if re.search(r"\b(price|venmo|cashapp|zelle|paypal|gift\s*card|promo\s*code|digital\s*code|$[0-9])\b", text, re.I):
        return True
    # Community-source gating
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
    if DEBUG:
        print("RANKED_TOP_URLS:", [h.get("url") for h in ranked[:8]])
    return ranked

# ----------------------------
# Triggers
# ----------------------------
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
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

# Fact-style queries (trigger direct snippet mode)
_FACT_QUERY_RE = re.compile(r"\b(last|latest|when|date|year|who|winner|won|result|release|final|most recent)\b", re.I)

# ----------------------------
# Web search backoffs & backends (FREE, no keys)
# ----------------------------
# ... search_with_duckduckgo_lib, _search_with_ddg_api, _search_with_wikipedia,
# ... _search_with_reddit, _search_with_github (already shown in part 1/2)

def _keywords_only(q: str) -> str:
    stop = {"where","what","who","when","which","the","and","for","with","from","into",
            "about","this","that","your","you","are","was","were","have","has","had",
            "a","an","of","to","in","on","by","at","last","latest","most","recent",
            "movie","film","release","won","winner","result","date","year"}
    toks = [w for w in _tokenize(q) if w not in stop]
    return " ".join(sorted(set(toks), key=toks.index)) or q

def _vertical_site_ladder(vertical: str) -> List[str]:
    if vertical == "sports":
        return ["formula1.com", "espn.com", "motorsport.com", "autosport.com", "the-race.com", "wikipedia.org"]
    if vertical == "entertainment":
        return ["imdb.com", "rottentomatoes.com", "metacritic.com", "boxofficemojo.com", "wikipedia.org"]
    if vertical == "tech":
        return ["learn.microsoft.com", "stackoverflow.com", "unix.stackexchange.com", "github.com", "wikipedia.org"]
    return ["wikipedia.org", "britannica.com", "biography.com", "history.com"]

def _build_query_by_vertical(q: str, vertical: str) -> str:
    if vertical == "entertainment":
        return f"{q} site:imdb.com OR site:rottentomatoes.com OR site:metacritic.com OR site:wikipedia.org"
    if vertical == "sports":
        return f"{q} site:formula1.com OR site:espn.com OR site:fifa.com OR site:wikipedia.org OR site:autosport.com OR site:motorsport.com OR site:the-race.com"
    if vertical == "tech":
        return f"{q} site:learn.microsoft.com OR site:stackoverflow.com OR site:unix.stackexchange.com OR site:github.com OR site:wikipedia.org"
    return f"{q} site:wikipedia.org OR site:britannica.com OR site:biography.com OR site:history.com"

def _try_all_backoffs(query: str, shaped: str, vertical: str, max_results: int) -> List[Dict[str,str]]:
    hits: List[Dict[str,str]] = []
    if DEBUG: print("BACKOFF_PASS1_SHAPED")
    # Pass 1: shaped (site-scoped) via DDG lib → API → wiki
    hits.extend(_search_with_duckduckgo_lib(shaped, max_results=max_results*2))
    if not hits:
        hits.extend(_search_with_ddg_api(shaped, max_results=max_results*2))
    if not hits:
        hits.extend(_search_with_wikipedia(query))
    if hits:
        return hits

    if DEBUG: print("BACKOFF_PASS2_PLAIN")
    # Pass 2: plain query (no site:)
    plain = query
    hits.extend(_search_with_duckduckgo_lib(plain, max_results=max_results*2))
    if not hits:
        hits.extend(_search_with_ddg_api(plain, max_results=max_results*2))
    if hits:
        return hits

    if DEBUG: print("BACKOFF_PASS3_KEYWORDS_ONLY")
    # Pass 3: keyword-only query
    kwq = _keywords_only(query)
    hits.extend(_search_with_duckduckgo_lib(kwq, max_results=max_results*2))
    if not hits:
        hits.extend(_search_with_ddg_api(kwq, max_results=max_results*2))
    if hits:
        return hits

    if DEBUG: print("BACKOFF_PASS4_SITE_LADDER")
    # Pass 4: per-site ladder (especially good for fact queries)
    for site in _vertical_site_ladder(vertical):
        q_site = f'{kwq} site:{site}'
        local = _search_with_duckduckgo_lib(q_site, max_results=max_results)
        if not local:
            local = _search_with_ddg_api(q_site, max_results=max_results)
        if local:
            hits.extend(local)
        if len(hits) >= max_results:
            break

    # Final safety: Wikipedia summary with keywords
    if not hits:
        if DEBUG: print("BACKOFF_FINAL_WIKI")
        wiki_fallback = _search_with_wikipedia(kwq)
        hits.extend(wiki_fallback)
    return hits

def _web_search(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    vertical = _detect_intent(query)
    shaped = _build_query_by_vertical(query, vertical)

    # Gather with tough fallbacks
    hits = _try_all_backoffs(query, shaped, vertical, max_results)

    # Add vertical extras (same as before)
    facty = bool(_FACT_QUERY_RE.search(query))
    if vertical == "tech":
        hits.extend(_search_with_reddit(query, limit=6))
        hits.extend(_search_with_github(query, limit=6))
    elif vertical in {"entertainment", "sports"}:
        if not facty:
            hits.extend(_search_with_reddit(query, limit=4))
    else:
        if not facty:
            hits.extend(_search_with_reddit(query, limit=3))

    if DEBUG:
        print("RAW_HITS_TOTAL", len(hits), "VERTICAL", vertical, "FACTY", facty)

    ranked = _rank_hits(query, hits, vertical)
    return ranked[:max_results] if ranked else []
# ----------------------------
# RAG + Orchestration
# ----------------------------
def _clean_text(txt: str) -> str:
    if not txt: return ""
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()

def _summarize_hits(query: str, hits: List[Dict[str,str]]) -> str:
    out = []
    for h in hits[:5]:
        title = _clean_text(h.get("title", ""))
        snip = _clean_text(h.get("snippet", ""))
        url = h.get("url", "")
        if snip and url:
            out.append(f"- {title} :: {snip} ({url})")
        elif url:
            out.append(f"- {title} ({url})")
    return "\n".join(out)

def handle_message(user_msg: str, max_new_tokens: int = 256) -> str:
    if not user_msg:
        return "I need some input."

    q = user_msg.strip()

    # 1. RAG injection (local HA states, sensors, etc.)
    rag_block = inject_context(q, top_k=5)
    if rag_block:
        try:
            ans = _chat_offline_singleturn(
                f"Context:\n{rag_block}\n\nUser: {q}\nAssistant:",
                max_new_tokens=max_new_tokens
            )
            if ans and "i don't know" not in ans.lower():
                return ans
        except Exception as e:
            if DEBUG: print("RAG_FAIL", e)

    # 2. Explicit trigger (wake words)
    if _should_use_web(q):
        hits = _web_search(q)
        if hits:
            summary = _summarize_hits(q, hits)
            try:
                return _chat_offline_singleturn(
                    f"Use the following search results to answer:\n{summary}\n\nUser: {q}\nAssistant:",
                    max_new_tokens=max_new_tokens
                )
            except Exception:
                return summary

    # 3. Facty queries (direct snippet mode)
    if _FACT_QUERY_RE.search(q):
        hits = _web_search(q, max_results=6)
        if hits:
            summary = _summarize_hits(q, hits)
            try:
                return _chat_offline_singleturn(
                    f"Search results:\n{summary}\n\nAnswer succinctly:",
                    max_new_tokens=max_new_tokens
                )
            except Exception:
                return summary

    # 4. Default offline attempt
    try:
        ans = _chat_offline_singleturn(q, max_new_tokens=max_new_tokens)
        if ans and "i don't know" not in ans.lower():
            return ans
    except Exception as e:
        if DEBUG: print("OFFLINE_FAIL", e)

    # 5. Web fallback if offline weak
    hits = _web_search(q)
    if hits:
        summary = _summarize_hits(q, hits)
        try:
            return _chat_offline_singleturn(
                f"Use the following search results to answer:\n{summary}\n\nUser: {q}\nAssistant:",
                max_new_tokens=max_new_tokens
            )
        except Exception:
            return summary

    # 6. Absolute final fallback
    return "I don't know."

# ----------------------------
# Main loop (CLI)
# ----------------------------
if __name__ == "__main__":
    print("Chatbot ready. Type messages (Ctrl+C to exit).")
    while True:
        try:
            msg = input("You: ").strip()
            if not msg:
                continue
            resp = handle_message(msg)
            print("Bot:", resp)
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            print("ERROR", e)