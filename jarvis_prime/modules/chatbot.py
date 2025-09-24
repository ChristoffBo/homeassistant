#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web fallback)
# - Default: offline LLM chat via llm_client.chat_generate
# - If wake words ("google it", "search the web") are present → Web search first
# - Otherwise: RAG first → Offline LLM → fallback to web if LLM fails
# - Filters: English-only, skip junk domains
# - Backoff: Wikipedia → DuckDuckGo lib (ddgs) → DuckDuckGo API
# - Summarizer disabled (raw notes only, no LLM summarization)

import os, re, json, time, html, requests, traceback
from typing import Dict, List, Tuple, Optional

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
        return _LLM.chat_generate(user_msg, max_new_tokens=max_new_tokens)
    except Exception as e:
        print(f"[llm] offline error: {e}")
        return ""
# ----------------------------
# Helpers
# ----------------------------
def _domain_of(url: str) -> str:
    try:
        return re.sub(r"^www\.", "", re.findall(r"https?://([^/]+)/?", url, re.I)[0].lower())
    except Exception:
        return ""

def _is_english_text(text: str, max_ratio: float = 0.2) -> bool:
    if not text:
        return True
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return (non_ascii / max(1, len(text))) <= max_ratio

_DENY_DOMAINS = [
    "zhihu.com","baidu.com","pinterest.","quora.com","tumblr.com",
    "vk.com","weibo.","4chan","8kun","/forum","forum.","boards.",
    "linktr.ee","tiktok.com","facebook.com","notebooklm.google.com"
]

def _is_deny_domain(url: str) -> bool:
    d = _domain_of(url)
    test = d + url.lower()
    return any(bad in test for bad in _DENY_DOMAINS)

def _tokenize(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2]

def _keyword_overlap(q: str, title: str, snippet: str, min_hits: int = 2) -> bool:
    qk = set(_tokenize(q))
    tk = set(_tokenize((title or "") + " " + (snippet or "")))
    stop = {"where","what","who","when","which","the","and","for","with","from","into",
            "about","this","that","your","you","are","was","were","have","has","had"}
    qk = {w for w in qk if w not in stop}
    return len(qk & tk) >= min_hits
def _is_junk_result(title: str, snippet: str, url: str, q: str) -> bool:
    if not title and not snippet:
        return True
    if _is_deny_domain(url):
        return True
    text = (title or "") + " " + (snippet or "")
    if not _is_english_text(text, max_ratio=0.2):
        return True
    if not _keyword_overlap(q, title, snippet, min_hits=2):
        return True
    if re.search(r"\b(price|venmo|cashapp|zelle|paypal|gift\s*card|promo\s*code|digital\s*code|[$][0-9])\b", text, re.I):
        return True
    return False

# Fact-style queries
_FACT_QUERY_RE = re.compile(r"\b(last|latest|when|date|year|who|winner|won|result|release|final|most recent|current leader)\b", re.I)
_CURRENT_YEAR = datetime.datetime.utcnow().year

def _rank_hits(q: str, hits: List[Dict[str,str]]) -> List[Dict[str,str]]:
    scored = []
    facty = bool(_FACT_QUERY_RE.search(q))
    for h in hits:
        url = (h.get("url") or "")
        title = (h.get("title") or "")
        snip = (h.get("snippet") or "")
        if not url:
            continue
        if _is_junk_result(title, snip, url, q):
            continue
        score = 0
        if "wikipedia.org" in url.lower():
            score += 8 if facty else 6
        if "github.com" in url.lower() or "stackoverflow.com" in url.lower():
            score += 5 if facty else 3
        if "espn.com" in url.lower() or "formula1.com" in url.lower():
            score += 5 if facty else 3
        if "imdb.com" in url.lower() or "rottentomatoes.com" in url.lower():
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
    ql = (q or "").lower().strip()
    for pattern in _WEB_TRIGGERS:
        if re.search(pattern, ql, re.I):
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
# Web search backends (FREE, no keys)
# ----------------------------
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

def _search_with_duckduckgo_lib(query: str, max_results: int = 6, region: str = "us-en") -> List[Dict[str, str]]:
    if _cb_open("ddg_lib"): 
        return []
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except ImportError:
        _cb_fail("ddg_lib")
        return []
    try:
        out: List[Dict[str, str]] = []
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results, region=region, safesearch="Moderate")
            for r in results:
                title = (r.get("title") or "").strip()
                url = (r.get("href") or "").strip()
                snippet = (r.get("body") or "").strip()
                if title and url:
                    out.append({"title": title, "url": url, "snippet": snippet})
        return out
    except Exception:
        _cb_fail("ddg_lib")
        return []
def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 6) -> List[Dict[str, str]]:
    if _cb_open("ddg_api"): 
        return []
    try:
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "0",
            "kl": "us-en"
        }
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        _cb_fail("ddg_api")
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
    return deduped

def _search_with_wikipedia(query: str, timeout: int = 6) -> List[Dict[str, str]]:
    if _cb_open("wikipedia"):
        return []
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
        _cb_fail("wikipedia")
        return []
    return []
# ----------------------------
# Query shaping + backoffs
# ----------------------------
def _build_query_all(q: str) -> str:
    """Return a cleaned query for global search (no vertical restriction)."""
    clean_q = q
    for pattern in _WEB_TRIGGERS:
        clean_q = re.sub(pattern, "", clean_q, flags=re.I).strip()
    clean_q = re.sub(r'\s+', ' ', clean_q).strip()
    return clean_q

def _try_all_backoffs(raw_q: str, shaped_q: str, max_results: int) -> List[Dict[str,str]]:
    hits: List[Dict[str,str]] = []
    wiki_hits = _search_with_wikipedia(raw_q)
    hits.extend(wiki_hits)
    if len(hits) >= max_results:
        return hits
    ddg_lib_hits = _search_with_duckduckgo_lib(shaped_q, max_results=max_results)
    hits.extend(ddg_lib_hits)
    if len(hits) >= max_results:
        return hits
    ddg_api_hits = _search_with_ddg_api(shaped_q, max_results=max_results)
    hits.extend(ddg_api_hits)
    return hits[:max_results]

# ----------------------------
# Web search orchestration
# ----------------------------
def _web_search(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    shaped = _build_query_all(query)
    hits = _try_all_backoffs(query, shaped, max_results)
    ranked = _rank_hits(query, hits, "general")
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
def _render_web_answer(notes: str, sources: List[Tuple[str, str]]) -> str:
    lines: List[str] = []
    if notes.strip():
        lines.append(notes.strip())
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

# ----------------------------
# Cleaners
# ----------------------------
def _clean_text(s: str) -> str:
    if not s:
        return s
    out = s.replace("\r","").strip()
    return re.sub(r"\n{3,}","\n\n",out).strip()
# ----------------------------
# Public entry
# ----------------------------
_CACHE: Dict[str,str] = {}

def handle_message(source: str, text: str) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    try:
        # 1) Web search if explicitly requested
        if _should_use_web(q):
            hits = _web_search(q, max_results=8)
            if hits:
                notes = _build_notes_from_hits(hits)
                sources = [(h.get("title") or h.get("url") or "", h.get("url") or "") for h in hits if h.get("url")]
                out = _render_web_answer(notes, sources)
                _CACHE[q] = out
                return out
            return "No results found."

        # 2) Try RAG context
        try:
            from rag import inject_context
            rag_block = inject_context(q, top_k=5)
        except Exception:
            rag_block = ""
        if rag_block:
            ans = _chat_offline_singleturn(q, max_new_tokens=256)
            clean_ans = _clean_text(ans)
            if clean_ans:
                return clean_ans

        # 3) Cache
        if q in _CACHE:
            return _CACHE[q]

        # 4) Offline LLM
        offline_ans = _chat_offline_singleturn(q, max_new_tokens=256)
        clean_offline = _clean_text(offline_ans)
        if clean_offline and clean_offline.lower() not in {"i don't know.","i dont know","unknown","no idea","i'm not sure","i am unsure"}:
            _CACHE[q] = clean_offline
            return clean_offline

        # 5) Fallback: web search
        hits = _web_search(q, max_results=8)
        if hits:
            notes = _build_notes_from_hits(hits)
            sources = [(h.get("title") or h.get("url") or "", h.get("url") or "") for h in hits if h.get("url")]
            out = _render_web_answer(notes, sources)
            _CACHE[q] = out
            return out

        return "I don't know."
    except Exception as e:
        print(f"HANDLE_MESSAGE_ERROR: {repr(e)}")
        traceback.print_exc()
        return "I don't know."

if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "Who is the current F1 leader Google it"
    print(handle_message("cli", ask))