#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web fallback)
# - Default: offline LLM chat via llm_client.chat_generate
# - Web mode if wake words are present OR offline LLM fails
# - Strategy: RAW DDGS → RAW Instant Answer → Wikipedia (opensearch→summary) → light enrichment
# - Debug: set {"chat_debug": true, "raw_debug": true} in /data/options.json to see internals/URLs

import os, re, json, time, html, requests, traceback
from typing import Dict, List, Tuple, Optional
from urllib.parse import quote as _urlquote

# ----------------------------
# Options (debug toggles)
# ----------------------------
CHAT_DEBUG = False
RAW_DEBUG = False
try:
    with open("/data/options.json", "r") as _f:
        _opts = json.load(_f)
        CHAT_DEBUG = bool(_opts.get("chat_debug", False))
        RAW_DEBUG = bool(_opts.get("raw_debug", False))
except Exception:
    pass

_HTTP_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "user-agent": "JarvisPrime/1.0 (+bot)"
}

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
# Helpers (very light filtering; heavy filters removed)
# ----------------------------
def _domain_of(url: str) -> str:
    try:
        return re.sub(r"^www\.", "", re.findall(r"https?://([^/]+)/?", url, re.I)[0].lower())
    except Exception:
        return ""

def _rank_hits_passthrough(hits: List[Dict[str,str]]) -> List[Dict[str,str]]:
    # Keep it simple to prove the pipeline works first.
    out = []
    seen = set()
    for h in hits:
        url = (h.get("url") or "").strip()
        if not url or not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        title = (h.get("title") or "").strip()
        snip = (h.get("snippet") or "").strip()
        out.append({"title": title, "url": url, "snippet": snip})
        if len(out) >= 10:
            break
    return out

def _smart_title_candidate(raw_q: str) -> str:
    stop = {"what","who","when","where","which","is","was","the","a","an","in","on","of","to","it","for","and"}
    toks = [t for t in re.findall(r"[a-zA-Z0-9']+", raw_q) if t.lower() not in stop]
    if not toks:
        return raw_q.strip().title()
    cand = " ".join(toks[:3]).strip()
    return cand.title()

def _build_better_query(raw_q: str) -> str:
    q = (raw_q or "").strip()
    # Minimal enrichment only; we do NOT force site: by default anymore.
    if re.search(r"\blast\b|\bmost\s+recent\b", q, re.I) and re.search(r"\btom\s+cruise\b", q, re.I):
        return "Tom Cruise latest movie filmography release date"
    if re.search(r"\bretire|retirement\b", q, re.I):
        return f"{q} career timeline date"
    return q

# ----------------------------
# Triggers
# ----------------------------
_WEB_TRIGGERS = [
    r"\bgoogle\s+it\b",
    r"\bgoogle\s+for\s+me\b",
    r"\bsearch\s+the\s+internet\b",
    r"\bsearch\s+the\s+web\b",
    r"\bweb\s+search\b",
    r"\binternet\s+search\b",
    r"\bcheck\s+internet\b",
    r"\bcheck\s+web\b",
]

def _should_use_web(q: str) -> bool:
    # Strip punctuation so "Google it." still matches
    ql = re.sub(r"[^\w\s]", " ", (q or "").lower())
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

# ----------------------------
# Web search backends (raw-first)
# ----------------------------
def _search_with_duckduckgo_lib(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception as e:
        if CHAT_DEBUG:
            print(f"[ddgs-import-error] {e}", flush=True)
        return []
    try:
        out: List[Dict[str, str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(
                query,
                region="wt-wt",
                safesearch="Moderate",
                timelimit=None,
                max_results=max_results
            ):
                title = (r.get("title") or "").strip()
                url = (r.get("href") or "").strip()
                snippet = (r.get("body") or "").strip()
                if title and url:
                    out.append({"title": title, "url": url, "snippet": snippet})
        if CHAT_DEBUG:
            print(f"[ddgs] query={query!r} results={len(out)}", flush=True)
        return out
    except Exception as e:
        if CHAT_DEBUG:
            print(f"[ddgs-runtime-error] {type(e).__name__}: {e}", flush=True)
        return []

def _search_with_ddg_api(query: str, max_results: int = 6, timeout: int = 5) -> List[Dict[str, str]]:
    try:
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "0",
            "kl": "us-en",
        }
        r = requests.get(url, params=params, timeout=timeout, headers=_HTTP_HEADERS, proxies={})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        if CHAT_DEBUG:
            print(f"[instant-answer-error] {type(e).__name__}: {e}", flush=True)
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

    if CHAT_DEBUG:
        print(f"[instant-answer] query={query!r} results={len(results)}", flush=True)
    return results[:max_results]

def _wiki_opensearch(title: str, timeout: int = 5) -> Optional[str]:
    try:
        api = "https://en.wikipedia.org/w/api.php"
        params = {"action": "opensearch", "search": title, "limit": "5", "namespace": "0", "format": "json"}
        r = requests.get(api, params=params, timeout=timeout, headers=_HTTP_HEADERS, proxies={})
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) >= 2 and data[1]:
            return str(data[1][0])
    except Exception as e:
        if CHAT_DEBUG:
            print(f"[wiki-opensearch-error] {type(e).__name__}: {e}", flush=True)
        return None
    return None

def _search_with_wikipedia_summary(title: str, timeout: int = 5) -> List[Dict[str, str]]:
    try:
        api = "https://en.wikipedia.org/api/rest_v1/page/summary/" + _urlquote(title)
        r = requests.get(api, timeout=timeout, headers=_HTTP_HEADERS, proxies={})
        if r.status_code == 200:
            data = r.json()
            page_title = data.get("title") or title
            desc = data.get("extract") or ""
            url = data.get("content_urls", {}).get("desktop", {}).get("page") or ""
            if page_title and url and desc:
                return [{"title": page_title, "url": url, "snippet": desc}]
    except Exception as e:
        if CHAT_DEBUG:
            print(f"[wiki-summary-error] {type(e).__name__}: {e}", flush=True)
        return []
    return []

def _search_with_wikipedia(query: str, timeout: int = 5) -> List[Dict[str, str]]:
    cand = _smart_title_candidate(query)
    title = _wiki_opensearch(cand, timeout=timeout) or cand
    res = _search_with_wikipedia_summary(title, timeout=timeout)
    if res:
        if CHAT_DEBUG:
            print(f"[wiki] title={title!r} results=1", flush=True)
        return res
    # try raw query too
    res = _search_with_wikipedia_summary(query, timeout=timeout)
    if CHAT_DEBUG:
        print(f"[wiki] title={query!r} results={len(res)}", flush=True)
    return res

def _web_search(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    # 1) RAW query via DDGS
    hits = _search_with_duckduckgo_lib(query, max_results=max_results)
    if hits:
        return hits
    # 2) RAW query via Instant Answer
    hits = _search_with_ddg_api(query, max_results=max_results)
    if hits:
        return hits
    # 3) Wikipedia robust fallback
    wk = _search_with_wikipedia(query)
    if wk:
        return wk
    # 4) LAST: mild enrichment
    q2 = _build_better_query(query)
    hits = _search_with_duckduckgo_lib(q2, max_results=max_results)
    if hits:
        return hits
    hits = _search_with_ddg_api(q2, max_results=max_results)
    return hits

# ----------------------------
# Render
# ----------------------------
def _render_web_answer(summary: str, sources: List[Tuple[str, str]], raw_hits: Optional[List[Dict[str,str]]] = None, debug_lines: Optional[List[str]] = None) -> str:
    lines: List[str] = []
    if summary.strip():
        lines.append(summary.strip())

    # Gentle source formatting
    if sources:
        dedup, seen = [], set()
        for title, url in sources:
            if not url or url in seen:
                continue
            seen.add(url)
            dedup.append((title, url))
        if dedup:
            lines.append("\nSources:")
            for title, url in dedup[:5]:
                dom = _domain_of(url)
                lines.append(f"• {title.strip() or dom} — {url.strip()}")

    if RAW_DEBUG and raw_hits:
        lines.append("\n[raw_top_urls]")
        for h in raw_hits[:5]:
            lines.append(f"- {h.get('title') or _domain_of(h.get('url') or '')} :: {h.get('url')}")

    if CHAT_DEBUG and debug_lines:
        lines.append("\n[debug]")
        lines.extend(f"- {d}" for d in debug_lines[:8])

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

    dbg: List[str] = []
    try:
        # Step 1: offline first
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        clean_ans = _clean_text(ans)

        offline_unknown = (not clean_ans) or (clean_ans.strip().lower() in {
            "i don't know.", "i dont know", "(no reply)", "i don't know", "unknown", "no idea"
        })
        if CHAT_DEBUG:
            dbg.append(f"offline_unknown={offline_unknown}")

        # Step 2: web if triggered OR offline was unknown
        if _should_use_web(q) or offline_unknown:
            raw_hits = _web_search(q, max_results=6)
            if CHAT_DEBUG:
                dbg.append(f"raw_hits={len(raw_hits)}")

            if raw_hits:
                hits = _rank_hits_passthrough(raw_hits)
                notes = _build_notes_from_hits(hits)
                summary = _chat_offline_summarize(q, notes, max_new_tokens=320).strip() if _llm_ready() else ""
                if CHAT_DEBUG:
                    dbg.append(f"summarizer_empty={not bool(summary)}")
                if not summary:
                    h0 = hits[0]
                    summary = h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources = [((h.get("title") or h.get("url") or ""), h.get("url") or "") for h in hits if h.get("url")]
                rendered = _render_web_answer(_clean_text(summary), sources, raw_hits=raw_hits, debug_lines=dbg)
                return rendered or (hits[0].get("snippet") or hits[0].get("title") or "No useful info.")

            # If truly nothing, say so with debug context if enabled
            return _render_web_answer("No results returned from any backend.", [], raw_hits=None, debug_lines=dbg)

        # Step 3: if we had a decent offline answer, return it; else final offline retry
        if clean_ans and not offline_unknown:
            return clean_ans
        fallback = _chat_offline_singleturn(q, max_new_tokens=240)
        return _clean_text(fallback) or "I don't know."
    except Exception as e:
        if CHAT_DEBUG:
            dbg.append(f"exception={type(e).__name__}: {e}")
        try:
            fallback = _chat_offline_singleturn(q, max_new_tokens=240)
            return _render_web_answer(_clean_text(fallback) or "I don't know.", [], raw_hits=None, debug_lines=dbg)
        except Exception as e2:
            if CHAT_DEBUG:
                dbg.append(f"fallback_exception={type(e2).__name__}: {e2}")
            return _render_web_answer("I don't know.", [], raw_hits=None, debug_lines=dbg)

# ----------------------------
# Shared cleaners (at end)
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
    ask = " ".join(sys.argv[1:]).strip() or "When did The Undertaker retire? Google it."
    print(handle_message("cli", ask))