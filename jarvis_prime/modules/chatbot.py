#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web fallback)
# - Default: offline LLM chat via llm_client.chat_generate
# - Web mode if wake words are present OR offline LLM fails
# - Topic aware routing:
#     * entertainment: IMDb/Wikipedia/RT/Metacritic (Reddit only vetted movie subs, and NOT for fact queries)
#     * tech/dev: GitHub + StackExchange + Reddit tech subs
#     * sports: F1/ESPN/FIFA official; Reddit excluded for fact queries
#     * general: Wikipedia/Britannica/Biography/History
# - Filters: English-only, block junk/low-signal domains, require keyword overlap
# - Ranking: authority + keyword overlap + strong recency for facts
# - Fallbacks: summarizer fallback + direct snippet mode for fact queries
# - Integrations: DuckDuckGo, Wikipedia, Reddit (vetted by vertical), GitHub (tech)
# - Free, no-register APIs only

import os, re, json, time, html, requests, datetime, traceback
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

    # kill commerce / resale / code-list spam
    if re.search(r"\b(price|venmo|cashapp|zelle|paypal|gift\s*card|promo\s*code|digital\s*code|$[0-9])\b", text, re.I):
        return True

    # community-source gating
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
    r"\bgoogle\s+it\b", r"\bgoogle\s+for\s+me\b",
    r"\bsearch\s+the\s+internet\b", r"\bsearch\s+the\s+web\b",
    r"\bweb\s+search\b", r"\binternet\s+search\b",
    r"\bcheck\s+internet\b", r"\bcheck\s+web\b",
]

def _should_use_web(q: str) -> bool:
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

# Fact-style queries (trigger direct snippet mode)
_FACT_QUERY_RE = re.compile(r"\b(last|latest|when|date|year|who|winner|won|result|release|final|most recent)\b", re.I)

# ----------------------------
# Web search backends (FREE, no keys)
# ----------------------------
def _search_with_duckduckgo_lib(query: str, max_results: int = 6, region: str = "us-en") -> List[Dict[str, str]]:
    try:
        from duckduckgo_search import DDGS  # type: ignore
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
        if DEBUG:
            print("DDG_LIB_HITS", len(out))
        return out
    except Exception as e:
        if DEBUG:
            print("DDG_LIB_ERR", repr(e))
        return []

def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 6) -> List[Dict[str, str]]:
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1", "skip_disambig": "0", "kl": "us-en"}
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        if DEBUG:
            print("DDG_API_ERR", repr(e))
        return []
    results: List[Dict[str, str]] = []
    def _push(title: str, url: str, snippet: str):
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
    if data.get("AbstractText") and data.get("AbstractURL"):
        _push(data.get("AbstractSource") or "DuckDuckGo Abstract", data.get("AbstractURL"), data.get("AbstractText"))
    for it in (data.get("Results") or []):
        _push(it.get("Text") or "", it.get("FirstURL") or "", it.get("Text") or "")
    for it in (data.get("RelatedTopics") or []):
        if "Topics" in it:
            for t in it["Topics"]:
                _push(t.get("Text") or "", t.get("FirstURL") or "", t.get("Text") or "")
        else:
            _push(it.get("Text") or "", it.get("FirstURL") or "", it.get("Text") or "")
    deduped, seen = [], set()
    for r in results:
        u = r.get("url") or ""
        if u and u not in seen:
            seen.add(u)
            deduped.append(r)
        if len(deduped) >= max_results:
            break
    if DEBUG:
        print("DDG_API_HITS", len(deduped))
    return deduped

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
    except Exception as e:
        if DEBUG:
            print("WIKI_ERR", repr(e))
        return []
    return []

def _search_with_reddit(query: str, limit: int = 6, timeout: int = 6) -> List[Dict[str,str]]:
    try:
        url = "https://www.reddit.com/search.json"
        headers = {"User-Agent": "JarvisPrimeBot/1.0"}
        r = requests.get(url, params={"q": query, "limit": str(limit), "sort": "relevance"}, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        hits: List[Dict[str,str]] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            sub = (d.get("subreddit") or "").strip()
            title = d.get("title") or ""
            snippet = d.get("selftext") or ""
            url = "https://www.reddit.com" + d.get("permalink", "")
            if title and url:
                hits.append({"title": f"Reddit/r/{sub}: {title}", "url": url, "snippet": snippet[:300]})
        if DEBUG:
            print("REDDIT_RAW_HITS", len(hits))
        return hits
    except Exception as e:
        if DEBUG:
            print("REDDIT_ERR", repr(e))
        return []

def _search_with_github(query: str, limit: int = 6, timeout: int = 6) -> List[Dict[str,str]]:
    hits = []
    try:
        repo_url = f"https://api.github.com/search/repositories?q={_urlquote(query)}&per_page={limit}"
        r = requests.get(repo_url, timeout=timeout, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "JarvisPrimeBot/1.0"})
        if r.status_code == 200:
            data = r.json()
            for item in data.get("items", []):
                hits.append({"title": f"GitHub Repo: {item.get('full_name')}", "url": item.get("html_url"), "snippet": (item.get("description") or "")[:300]})
    except Exception as e:
        if DEBUG:
            print("GITHUB_REPO_ERR", repr(e))
    try:
        issues_url = f"https://api.github.com/search/issues?q={_urlquote(query)}&per_page={limit}"
        r = requests.get(issues_url, timeout=timeout, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "JarvisPrimeBot/1.0"})
        if r.status_code == 200:
            data = r.json()
            for item in data.get("items", []):
                hits.append({"title": f"GitHub Issue: {item.get('title')}", "url": item.get("html_url"), "snippet": (item.get("body") or "")[:300]})
    except Exception as e:
        if DEBUG:
            print("GITHUB_ISSUE_ERR", repr(e))
    if DEBUG:
        print("GITHUB_RAW_HITS", len(hits))
    return hits

# ----------------------------
# Query shaping by vertical
# ----------------------------
def _build_query_by_vertical(q: str, vertical: str) -> str:
    if vertical == "entertainment":
        return f"{q} site:imdb.com OR site:rottentomatoes.com OR site:metacritic.com OR site:wikipedia.org"
    if vertical == "sports":
        return f"{q} site:formula1.com OR site:espn.com OR site:fifa.com OR site:wikipedia.org OR site:autosport.com OR site:motorsport.com OR site:the-race.com"
    if vertical == "tech":
        return f"{q} site:learn.microsoft.com OR site:stackoverflow.com OR site:unix.stackexchange.com OR site:github.com OR site:wikipedia.org"
    return f"{q} site:wikipedia.org OR site:britannica.com OR site:biography.com OR site:history.com"

# ----------------------------
# Web search orchestration
# ----------------------------
def _web_search(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    vertical = _detect_intent(query)
    shaped = _build_query_by_vertical(query, vertical)

    hits: List[Dict[str,str]] = []
    hits.extend(_search_with_duckduckgo_lib(shaped, max_results=max_results*2))
    if not hits:
        hits.extend(_search_with_ddg_api(shaped, max_results=max_results*2))
    if not hits:
        hits.extend(_search_with_wikipedia(query))

    facty = bool(_FACT_QUERY_RE.search(query))
    if vertical == "tech":
        hits.extend(_search_with_reddit(query, limit=6))
        hits.extend(_search_with_github(query, limit=6))
    elif vertical == "entertainment":
        if not facty:
            hits.extend(_search_with_reddit(query, limit=4))
    elif vertical == "sports":
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
# Render
# ----------------------------
def _render_web_answer(summary: str, sources: List[Tuple[str, str]]) -> str:
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

def _build_notes_from_hits(hits: List[Dict[str,str]]) -> str:
    notes = []
    for h in hits[:6]:
        t = html.unescape((h.get("title") or "").strip())
        s = html.unescape((h.get("snippet") or "").strip())
        if t or s:
            notes.append(f"- {t} — {s}")
    return "\n".join(notes)

# ----------------------------
# Public entry
# ----------------------------
def handle_message(source: str, text: str) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    try:
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        clean_ans = _clean_text(ans)
        offline_unknown = (not clean_ans) or (clean_ans.strip().lower() in {
            "i don't know.", "i dont know", "(no reply)", "unknown", "no idea", "i'm not sure", "i am unsure"
        })

        if _should_use_web(q) or offline_unknown:
            hits = _web_search(q, max_results=8)
            if DEBUG:
                print("POST_FILTER_HITS", len(hits))

            if hits:
                # direct snippets for facty prompts
                if _FACT_QUERY_RE.search(q):
                    snippets = []
                    for h in hits[:3]:
                        title = h.get('title') or ''
                        snip  = h.get('snippet') or ''
                        if title and snip:
                            snippets.append(f"{title} — {snip}")
                        else:
                            snippets.append(title or snip)
                    sources = [((h.get("title") or h.get("url") or ""), h.get("url") or "") for h in hits if h.get("url")]
                    return _render_web_answer("\n".join(snippets), sources)

                # synthesizer for non-fact questions
                notes = _build_notes_from_hits(hits)
                summary = _chat_offline_summarize(q, notes, max_new_tokens=320).strip()
                if not summary or summary.lower() in {"i am unsure", "i'm not sure", "i don't know"}:
                    h0 = hits[0]
                    summary = h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources = [((h.get("title") or h.get("url") or ""), h.get("url") or "") for h in hits if h.get("url")]
                return _render_web_answer(_clean_text(summary), sources)

        if clean_ans and not offline_unknown:
            return clean_ans
        fallback = _chat_offline_singleturn(q, max_new_tokens=240)
        return _clean_text(fallback) or "I don't know."
    except Exception as e:
        if DEBUG:
            traceback.print_exc()
        try:
            fallback = _chat_offline_singleturn(q, max_new_tokens=240)
            return _clean_text(fallback) or "I don't know."
        except Exception:
            return "I don't know."

# ----------------------------
# Shared cleaners
# ----------------------------
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

if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "When was the last Robin Hood movie released? Google it"
    print(handle_message("cli", ask))