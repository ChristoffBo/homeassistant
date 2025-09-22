#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web fallback)
# - Default: offline LLM chat via llm_client.chat_generate
# - Web mode if wake words are present OR offline LLM fails
# - Filters: English-only, block junk/low-signal domains, require keyword overlap
# - Fallback order: DuckDuckGo lib → DuckDuckGo API → Wikipedia → offline LLM

import os, re, json, time, html, requests, traceback
from typing import Dict, List, Tuple, Optional
from urllib.parse import quote as _urlquote

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
# Helpers & filters
# ----------------------------
_AUTHORITY_DOMAINS = [
    "wikipedia.org", "britannica.com", "biography.com",
    "graceland.com", "history.com", "smithsonianmag.com",
]
_DENY_DOMAINS = [
    "fightercontrol.co.uk", "pinterest.", "quora.com", "tumblr.com",
    "vk.com", "weibo.", "zhihu.com", "baidu.com",
    "4chan", "8kun", "/forum", "forum.", "boards.",
]

def _tokenize(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2]

def _keyword_overlap(q: str, title: str, snippet: str, min_hits: int = 2) -> bool:
    qk = set(_tokenize(q))
    tk = set(_tokenize((title or "") + " " + (snippet or "")))
    stop = {"where","what","who","when","which","the","and","for","with","from","into",
            "about","this","that","your","you","are","was","were","have","has","had"}
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

def _is_authority(url: str) -> bool:
    d = _domain_of(url)
    return any(d.endswith(ad) for ad in _AUTHORITY_DOMAINS)

def _is_junk_result(title: str, snippet: str, url: str, q: str) -> bool:
    if not title and not snippet:
        return True
    if _is_deny_domain(url):
        return True
    text = (title or "") + " " + (snippet or "")
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    if non_ascii / max(1, len(text)) > 0.3:
        return True
    if not _keyword_overlap(q, title, snippet, min_hits=2):
        return True
    return False

def _rank_hits(q: str, hits: List[Dict[str,str]]) -> List[Dict[str,str]]:
    scored = []
    for h in hits:
        url = (h.get("url") or "")
        title = (h.get("title") or "")
        snip = (h.get("snippet") or "")
        if not url:
            continue
        if _is_junk_result(title, snip, url, q):
            continue
        score = 0
        if _is_authority(url):
            score += 5
        score += min(len(snip)//120, 3)
        overlap_bonus = len(set(_tokenize(q)) & set(_tokenize(title + " " + snip)))
        score += min(overlap_bonus, 4)
        scored.append((score, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored]

def _build_better_query(raw_q: str) -> str:
    q = (raw_q or "").strip()
    if re.search(r"\b(elvis)\b", q, re.I) and re.search(r"\bfamily|parents|children|wife|where\b", q, re.I):
        return ("Elvis Presley family members residence relatives Lisa Marie Presley Priscilla Presley "
                "site:wikipedia.org OR site:britannica.com OR site:biography.com OR site:graceland.com")
    return f"{q} site:wikipedia.org OR site:britannica.com OR site:biography.com"

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
    ql = (q or "").lower()
    return any(re.search(p, ql, re.I) for p in _WEB_TRIGGERS)

# ----------------------------
# Web search backends
# ----------------------------
def _search_with_duckduckgo_lib(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception:
        return []
    try:
        out: List[Dict[str, str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, region="wt-wt", safesearch="Moderate"):
                title = (r.get("title") or "").strip()
                url = (r.get("href") or "").strip()
                snippet = (r.get("body") or "").strip()
                if title and url:
                    out.append({"title": title, "url": url, "snippet": snippet})
        return out
    except Exception:
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
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
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
        url = r.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            deduped.append(r)
        if len(deduped) >= max_results:
            break
    return deduped

def _search_with_wikipedia(query: str, timeout: int = 5) -> List[Dict[str, str]]:
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

def _web_search(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    q2 = _build_better_query(query)
    hits = _search_with_duckduckgo_lib(q2, max_results=max_results*2)
    if not hits:
        hits = _search_with_ddg_api(q2, max_results=max_results*2)
    ranked = _rank_hits(query, hits)
    if ranked:
        return ranked[:max_results]
    m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", query)
    title = m.group(1) if m else query
    return _search_with_wikipedia(title)

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
        # Step 1: offline first
        ans = _chat_offline_singleturn(q, max_new_tokens=256)
        clean_ans = _clean_text(ans)

        offline_unknown = (not clean_ans) or (clean_ans.strip().lower() in {
            "i don't know.", "i dont know", "(no reply)", "i don't know", "unknown", "no idea"
        })

        # Step 2: web if triggered OR offline was unknown
        if _should_use_web(q) or offline_unknown:
            hits = _web_search(q, max_results=6)
            if hits:
                notes = _build_notes_from_hits(hits)
                summary = _chat_offline_summarize(q, notes, max_new_tokens=320).strip()
                if not summary:
                    h0 = hits[0]
                    summary = h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources = [((h.get("title") or h.get("url") or ""), h.get("url") or "") for h in hits if h.get("url")]
                return _render_web_answer(_clean_text(summary), sources)

        # Step 3: if we had a decent offline answer, return it; else final offline retry
        if clean_ans and not offline_unknown:
            return clean_ans
        fallback = _chat_offline_singleturn(q, max_new_tokens=240)
        return _clean_text(fallback) or "I don't know."
    except Exception:
        try:
            fallback = _chat_offline_singleturn(q, max_new_tokens=240)
            return _clean_text(fallback) or "I don't know."
        except Exception:
            return "I don't know."

# ----------------------------
# Shared cleaners (kept at end to allow references above)
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
    ask = " ".join(sys.argv[1:]).strip() or "Where is Elvis Presley family? Google it"
    print(handle_message("cli", ask))